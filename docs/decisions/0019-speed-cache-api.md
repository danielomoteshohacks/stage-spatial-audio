# 0019. Speed, the per-track cache, outputs and the /rerender API

- Status: accepted
- Date: 2026-11-24

## Decision

- **Speed.** Profiling the first scene render (21 s per 30 s) found 9 s in smoothing the
  section-openness curve at the audio rate (an 86 000-tap window) and 4 s in the HPSS median
  filters. The curve is now built at 100 values per second and interpolated, and HPSS runs at a
  1024 hop with a 9-frame median (the same 0.2 s as 17 frames at 512). All long convolutions use
  scipy's `oaconvolve`, which partitions the signal into FFT blocks (overlap-add partitioned
  convolution). The room responses are cached per (space, direction, distance, send). Only one
  stem's decomposition is alive at a time.
- **Cache.** `stage.service` keys each excerpt by the SHA-256 of the file's bytes and the
  excerpt (24 hex characters, the `track_id` in run.json). Under `<work root>/tracks/<id>/` the
  pipeline keeps the excerpt (original.flac), the separated stems (float32 .npz with the
  separator's record), the song analysis and the genre decision, for the same 30-minute
  time-to-live as the outputs (a re-render extends it). Changing the space, the character, the
  motion, the genre or the plan never re-separates, which saves the visitor's GPU quota.
- **Outputs** per run: original.flac and spatial.flac (24-bit), objects/*.flac (the per-object
  spatial stems, with `low_end`, summing exactly to spatial.flac), plan.json, report.json,
  run.json, and on request bed_7_1_4.wav (12 channels, 24-bit, ITU-R BS.2051 System J order).
- **API.** `/process` takes file, mode, profile (space), beta, start, length, genre ("auto" or a
  template), motion depth, an optional plan (JSON) and the 7.1.4 flag. `/rerender` takes a
  track id and the same settings (or an edited plan) with no upload. Both stream one update per
  stage; the final update carries the run report, the guard report, the plan, the track id and
  the paths of plan.json, report.json and the bed. Only the teacher separator runs inside
  @spaces.GPU; analysis, rendering and our separator run on the CPU.

## Measured (`benchmarks/render_times.py`, 30 s at 44.1 kHz, 4 vCPU build machine)

| Configuration | Run | Render (s) | Whole pipeline (s) | Guard |
|---|---|---|---|---|
| v1 Lite (max) | cold | 2.49 | 9.17 | review |
| v1 Lite (max) | warm | 1.53 | 8.01 | review |
| v2 Lite (studio) | cold | 4.95 | 11.67 | pass |
| v2 Lite (studio) | warm | 4.12 | 10.82 | pass |
| v2 stems scene (living room) | cold | 15.58 | 22.50 | review (alignment estimate, see below) |
| v2 stems scene (living room) | warm | 8.43 | 15.96 | review |

Targets: Lite render under 10 s (met, 4.1 to 5.0 s); full plan render under 40 s plus separation
(met, 8.4 to 15.6 s). The "whole pipeline" adds loading, the guard report (about 4 s for 30 s),
analysis and writing. The Space's CPU differs from this machine; its numbers will be read from
run.json's stage durations on the live Space.

## The guard's alignment estimate, again

The living-room scene first read -2.8 ms (physically impossible: the renderer is causal). The
estimator now takes the earliest correlation peak within 6 dB of the largest, accepting a peak
before zero only when it is nearly the largest. It reads 0.02 to 0.16 ms on 16 of 18 test
renders and finds every injected shift exactly (30, 100, 200, -40 and -150 samples, also
inverted). The Lite living-room scene still reads 1.9 ms and is reported as "review".
