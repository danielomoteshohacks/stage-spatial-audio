# 0027. Whole songs, streamed while they render; speed; and what v3 is judged by

- Status: accepted (the targets section is completed in Phase 6)
- Date: 2026-11-25

## Decision

**Whole songs by default.** A job (`stage.stream.job`) loads the whole file (an `excerpt` option
remains: `start_s` and `seconds`), analyses the whole mix (half a second for four minutes), and
processes it in chunks: the first 8 s, then 20 s chunks, each overlapping the previous by 1.5 s.
Each chunk is separated with 2 s of context either side (the cascade caches per content hash), the
plan is built from the first chunk's leaves, events are detected per chunk on the song's clock,
the chunk is rendered, and `stage.stream.segments.Assembler` joins it to the previous one with
sin^2 cross-fades over the overlap (the two ramps sum to one). Tested: an identity renderer returns
the input exactly for every song length tried (2e-6), and chunks that differ by 0.35 dB alternately
are blended with no step larger than the signal's own.

**Progressive delivery.** Each finished region is encoded as a segment and served at
`/v3/jobs/{id}/seg/{name}` while the rest renders; `/v3/jobs/{id}` reports chunks done, segments
ready (start, duration, context to trim) and time to first sound. Playback starts at the first
segment. Segments carry 50 ms of the neighbouring audio at each end (`pre`, `post`), which the
client discards, so two independently encoded segments meet with only the codec's noise between
them (tested against encoding the whole render as one stream: no worse than 1 dB).

**Delivery.** Opus in Ogg at 160 kb/s for playback (AAC-LC 192 kb/s where the client asks for it
and ffmpeg is installed; the Space gets ffmpeg from `packages.txt`); FLAC (24 bit) and the 7.1.4 WAV
are downloads. About 1.2 MB a minute.

**ZeroGPU.** The job runs inside a Gradio event (`/v3_process`) because ZeroGPU charges a
visitor's quota only for GPU calls made in the event they started; the event streams state
snapshots and the segments are fetched over plain HTTP from the same app (`stage.server.api`,
FastAPI mounted around the Gradio app with CORS). Off the Space the same routes run the job on a
worker thread.

**Speed** (`benchmarks/render_times_v3.py`, `GET /v3/bench`), float32 throughout, batched
partitioned convolution with cached filter spectra (`scene3.fastconv`), sources that share a filter
summed before they are convolved when stems are not wanted, the crossover applied once to the sum
instead of to every leaf (the filters are linear), a frequency-domain crossover and a loudness
match that filters once and iterates on per-step sums (`scene3.fastdsp`), filters built once per
distinct 1 degree position, and the guard run in windows on long songs (`stream.guard`).
No Python loop touches samples; numba was not needed.

| 30 s excerpt, 15 leaves, this machine (4 cores; the Space's hardware was not reachable) | seconds | real-time factor |
|---|---|---|
| v2, stems scene, living room, cold / warm | 14.6 / 8.5 | 0.49 / 0.28 |
| v3 before the optimisations (commit e975d5f), cold / warm | 23.4 / 22.9 | 0.78 / 0.76 |
| v3 now, with per-object stems, cold / warm | 5.0 / 4.7 | 0.17 / 0.16 |
| v3 now, no stems (the streaming path), cold / warm | 2.8 / 2.25 | 0.09 / 0.075 |

Stages of the warm no-stems render (seconds per 30 s): split 0.11, sources 1.4, convolve 0.35,
neutrality 0.39; with stems the convolution is 2.1 s because every object has its own inverse
transforms. A whole song of 163 s (generated, model-free leaves) took 46 s end to end: analysis 0.6 s,
separation 16 s (the model-free decomposition), render 5.5 s (RTF 0.033), encoding 3.3 s,
guard 20 s (it was 81 s before the windowing); **time to first sound 1.9 s** with the model-free
provider. With real separation the first chunk's separation time is added; it is not measured here
(no GPU; decision 0023), so the under-30-s target for a new upload with the `fast` preset is
**not demonstrated**. What is demonstrated is that everything after separation costs 1.5 s for the
first 8 s chunk.

## Honest limits

- The guard on a long song checks five 20 s windows and the whole song's loudness and true peak,
  and says so in `coverage`; a pass means "inside thresholds where it was measured".
- Opus is perceptual: on noise-rich material its waveform SNR is low and says nothing about
  quality. The listening test decides; the seam test only shows the joints add nothing.
- Per-chunk timbre and loudness matching mean level can differ by a few tenths of a dB between
  chunks; the cross-fade blends it.
