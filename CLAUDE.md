# CLAUDE.md

Guidance for Claude Code when working in this repository. Read this first, every session.

## What this project is

Stage (working brand name: SoundStage) is a spatial audio engine that lives inside the music app.
It works on any song and any phone, needs no Dolby hardware, and keeps the artist in control.
It is an independent proposal, not affiliated with or endorsed by Spotify, Apple or Dolby.

Core method, Pan-Anchored Spatial Rendering (PASR): keep each sound where the stereo mix already
puts it, widen those positions around the listener with an order-preserving warp, give each role
(kick, bass, vocal, pads) its own distance, add a believable room, and check every render against
the original with a fidelity guard. Three complete tiers: Lite (no neural network, real time on
the device), Standard (small separation model, offline), Studio (separation plus refiner, offline).

Long-term goals: a browser demo where any dropped song plays spatially, then spatial podcasts and
discussion shows. Everything below serves the music engine first.

## Read these before designing anything

- `docs/specs/` : two PDFs. Where they disagree, Chapters 19 to 26 of the v2 specification win.
- `docs/decisions/` : why each major choice was made. Add a new record when a decision changes.
- `docs/architecture.md`, `docs/roadmap.md`, `experiments/README.md` (hypotheses H1 to H10 with gates).

## Current state (verify with `git log --oneline` and `ls src/stage/*` before trusting this)

Done: repository scaffold and CI, JSON schemas (plan, report, consent), `stage.analysis`
(exact-reconstruction STFT, panning, coherence, primary and ambient split), `stage.render.sectors`
(13 sectors, Gaussian weights, widen warp).

Slice 1, "Hear it", is in progress. Next tasks, in order:

1. Small fixes to the sector tests and docs, on a branch:
   - `tests/unit/test_sectors.py`: replace the two-centre check with a parametrised test that
     every one of the 13 centres peaks in its own sector.
   - `apply_sectors` docstring: state that `power` is (frames, bins) with no channel axis,
     weights are (13, frames, bins), summing over axis 0 returns the input exactly, and that long
     songs must be processed in blocks of frames (a 4-minute song's weights need over 1 GB in float64).
   - Add `.gitattributes` with `* text=auto eol=lf` (the repo is edited on Windows).
2. `src/stage/render/headmodel.py`: a closed-form head model, no dataset downloads.
   - `ear_delays_s(az_deg)`: Woodworth, lat = arcsin(sin(az)), itd = (a/c) * (|lat| + |sin(lat)|),
     a = 0.0875 m, c = 343 m/s. Verified values: 0.656 ms at 90 degrees, 0.261 ms at 30 degrees,
     and 150 degrees gives the same as 30 degrees (rear mirrors onto the front).
   - `head_shadow(theta_deg, freqs_hz)`: Brown and Duda one-pole-one-zero filter.
     Verified at 8 kHz: near ear +5.94 dB, far ear -9.95 dB; at 1 kHz: +3.37 and -1.94 dB.
   - `sector_filters(azimuths_deg, n_fft=2048, sample_rate=44100)`: shape (n_az, 2, n_fft // 2 + 1),
     axis 1 is left then right ear. Mirror symmetry and a roughly 29-sample inter-ear lag at 90 degrees
     are tested.
3. First renderer plus `scripts/render_clip.py`: STFT, analysis, per-sector filtering, ambient to a
   decorrelated tail, inverse STFT, write a 24-bit WAV that can be heard on headphones.
   Decide explicitly whether complex spectra are split with `w` or `sqrt(w)` (the sector weights
   sum to 1 in power), and add a test that energy is conserved before filtering.
4. Fidelity guard basics: alignment, loudness, timbre deviation, low-end correlation.

## Conventions

- Python 3.10+ in `src/stage/`. Libraries so far: numpy, scipy, soundfile. Ask before adding any.
- Local machine runs Python 3.14.3; CI runs 3.11 and 3.12. Keep code valid on all of them.
- Lint: `ruff check .` (line length 100, rules E, F, I, B). Tests: `pytest -q`. Both must pass before every commit.
- Sorted imports, absolute imports (`from stage.render.sectors import ...`), `zip(..., strict=True)`,
  `raise ... from None` inside `except`.
- float64 everywhere in the reference code; type hints and docstrings on public functions.
- Audio arrays are (channels, samples); spectrograms are (channels, frames, bins).
- Azimuth: 0 is straight ahead, positive is to the right.
- Comments explain why, not what. No emojis anywhere in the codebase or commit messages.
- The Python code is the reference implementation. A Rust port (`stage-core/`) must later match its
  golden files, so keep the maths simple and deterministic.

## Workflow

- One short branch per task (`feat/...`, `fix/...`, `docs/...`, `test/...`), then a pull request and a
  squash merge once CI is green. Do not commit straight to `main`.
- Conventional Commit messages: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, `build:`, `ci:`, `chore:`.
- Every change comes with tests. Every claim comes with a measurement, a sample size and an interval.
  Report failures and negative results honestly; never invent numbers or placeholder results.
- Surgical edits over rewrites. Show the diff and the reasoning for anything non-trivial.

## Hard rules

- Never commit audio, model weights or datasets. Record them in `data/` and `models/` manifests with source and licence.
- Use only music Daniel owns, has written permission to use, or that is openly licensed.
- Never use Spotify audio, previews or API data for training, testing or demos.
- Treat any pretrained weight as research-only until its licence is confirmed in writing.
- Do not copy patented binaural virtualiser structures; flag any doubt.
- Keep the "independent proposal" disclaimer wherever the project is presented.

## Working with Daniel

- He wants to be involved in building, not handed finished work. Explain the reasoning briefly,
  work in small steps, and let him run the verification commands and see the result.
- His mobile data is very limited. Ask before any large download (models, datasets, big packages).
- His laptop runs on mains power and outages are common. Commit small and often; push when online.
- Windows with VS Code. The integrated terminal may be PowerShell (the virtual environment is `.venv`)
  or Git Bash; give commands that work in both, or say which one.
- He writes casually. Match the tone, but keep the engineering precise.
