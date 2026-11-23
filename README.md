# SoundStage

**A spatial audio engine that lives inside the music app: any song, any phone, no Dolby hardware, artist in control.**

[![CI](https://github.com/danielomoteshohacks/stage-spatial-audio/actions/workflows/ci.yml/badge.svg)](https://github.com/danielomoteshohacks/stage-spatial-audio/actions/workflows/ci.yml)
[![Licence](https://img.shields.io/badge/licence-Apache--2.0-blue.svg)](LICENSE)
![Status](https://img.shields.io/badge/status-early%20development-orange.svg)
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

Most stereo upmixers invent positions. SoundStage does the opposite: **it keeps every sound where the stereo
mix already puts it**, spreads those positions around the listener, gives each role an appropriate
distance, and adds a believable room. A fidelity guard compares every render with the original so the
record is never rewritten.

```mermaid
flowchart LR
    A[Stereo input] --> B[Pan and coherence analysis]
    B --> C[Primary and ambient split<br/>primary + ambient = input]
    C --> D[Pan sectors, widened<br/>order preserved]
    D --> E[HRTF filtering]
    C --> F[Decorrelated ambient tail]
    E --> G[Role-based distance and room]
    F --> G
    G --> H[Timbre bound and fidelity guard]
    H --> I[Binaural output]
```

Around that renderer sits the listening bench (decision 0009): a small Python service and a web
app that plays the original and the spatial render in sync.

```mermaid
flowchart LR
    U[Web app<br/>web/, in the browser] -- "upload, progress events,<br/>24-bit FLAC" --> A[Gradio backend<br/>space/app.py]
    A --> S[Service<br/>stage.service]
    S --> P[Pipeline<br/>stage.pipeline]
    P --> D[Separation<br/>Demucs, optional]
    P --> R[Renderer<br/>stage.render]
    P --> L[Levels<br/>stage.guard.levels]
```

Four properties define the design:

1. **Position-preserving.** A sound left of another in the original stays left of it.
2. **Role-aware.** Kick, bass and lead vocal stay close and dry; pads and effects get space.
3. **Faithful.** Long-term tone, low end, loudness and timing are checked against the original.
4. **Light.** The lightest tier needs no neural network and is designed to run in real time on a phone.

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

The listening bench runs on your own machine in two terminals (Python 3.10+, Node 20+):

```bash
# 1. Backend (repository root): Lite only. Add ",separation" for Demucs stems (installs torch).
python -m pip install -e ".[backend]"
python space/app.py                      # http://127.0.0.1:7860

# 2. Web app
cd web && npm ci && npm run dev          # http://localhost:5173
```

Drop a track, choose an excerpt, render, then switch between Original and Spatial with the big
toggle or the space bar. Tracks are processed and deleted after 30 minutes; use audio you own or
may use. Without the separation extra, Stems mode falls back to Lite and the page says so.

From the command line, without the web app:

```bash
python scripts/process_track.py track.flac --mode lite --start 30 --seconds 30 --out-dir runs/a
```

The backend also deploys to a Hugging Face ZeroGPU Space ([`space/README.md`](space/README.md)),
and the web app to Cloudflare Pages ([`web/README.md`](web/README.md)).

## Status

Early development. Nothing here yet makes a perceptual claim: the profiles carry objective proxy
measurements only (decision 0007), and the blind tests have not been run.

- The listening bench works end to end in Lite mode on a laptop (measured in
  [`docs/log.md`](docs/log.md)). Real Demucs separation and the ZeroGPU Space have not been run
  yet; the code for both is written against their documented APIs.

- [ ] **Slice 1, Hear it:** one clip spatialised by Lite in Python
- [ ] **Slice 2, Prove it:** measurements and a first blind test
- [ ] **Slice 3, Make it smart:** stems, roles, style templates
- [ ] **Slice 4, Make it light:** Rust core and WebAssembly, real time in the browser
- [ ] **Slice 5, Show it:** demo, efficiency chart, write-up, video

See [`docs/roadmap.md`](docs/roadmap.md).

## Repository layout

| Path | Purpose | Status |
|---|---|---|
| [`src/stage/`](src/stage/) | Python reference implementation (the oracle) | active |
| [`schemas/`](schemas/) | JSON Schemas for the plan, report and consent files | active |
| [`tests/`](tests/) | Unit, property, golden-file and integration tests | active |
| [`docs/`](docs/) | Specifications, architecture, roadmap, decision records | active |
| [`experiments/`](experiments/) | Hypotheses, gates and results | active |
| [`stage-core/`](stage-core/) | Rust real-time core, compiled to WebAssembly | planned |
| [`tools/hrtf-pack/`](tools/hrtf-pack/) | Converts open SOFA data into a compact pack | planned |
| [`web/`](web/) | Listening bench: sync A/B player, progress, run report | active |
| [`space/`](space/) | Gradio backend for a laptop or a Hugging Face Space | active |
| [`android/`](android/) | Optional Android client | planned |
| [`configs/`](configs/) | Style templates, modes, guard thresholds | planned |
| [`models/`](models/) | Model manifest (files are never committed) | planned |
| [`data/`](data/) | Dataset manifest (audio is never committed) | planned |
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
datasets (used with attribution). Some structures used in commercial binaural virtualisers are
patented; SoundStage avoids copying them and a freedom-to-operate check is planned before any product claim.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Experiments use the Experiment issue template.

## Licence

Code is licensed under [Apache-2.0](LICENSE). Models and datasets keep their own licences.
