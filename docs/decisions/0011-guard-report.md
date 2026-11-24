# 0011. Every render gets a fidelity report, and the excerpt starts at the loudest part

- Status: accepted
- Date: 2026-11-24

## Context

The owner listened to v1 on real songs and heard artifacts. Until now nothing measured them:
`stage.guard` had an RMS match and peak safety (`levels`) on main, and the alignment, timbre and
low-end checks of PR #9 sat unmerged on `feat/guard`. A render that changes the bass, smears a
snare or leaves musical noise must be caught before a listener hears it, with the place to listen.

Listening tests also landed on intros: the default excerpt was 30 s from 30 s in.

## Decision

1. PR #9's `stage.guard.checks` and `scripts/measure_sector_sum.py` are on main; its decision is
   renumbered 0010 (0009 is the listening bench).
2. `stage.guard.report.build_report` writes `report.json` (schemas/report.schema.json) for every
   render, as a new pipeline stage `guard` between `levels` and `write`. Its parts:
   - **Integrated loudness, ITU-R BS.1770-4** (`stage.guard.loudness`): K-weighting, 400 ms
     blocks at 75 percent overlap, absolute gate -70 LUFS, relative gate -10 LU. At 48 kHz the
     standard's coefficient table is used; at other rates the two biquads are re-derived from the
     analogue prototype parameters Brecht De Man fitted to that table. Cross-checked in the tests
     against pyloudnorm (dev dependency, MIT): identical to its `DeMan` filters, and within
     0.05 LU of its default RBJ filters, inside the 0.1 LU requirement. A 0 dBFS 997 Hz sine in one
     channel reads -3.01 LUFS, the standard's calibration point.
   - **True peak, BS.1770-4 Annex 2**: 4x oversampling (2x at 96 kHz and above) with a polyphase
     interpolator; the test sine at fs/4 with 45 degree phase has sample peaks at -3.01 dBFS and
     reads 0.0 dBTP.
   - **Downmix difference**: the mid (L + R) band levels of the render against the original in
     three broad bands (20 to 250 Hz, 250 Hz to 4 kHz, 4 to 16 kHz) after removing the overall
     offset: what a phone speaker or a mono Bluetooth speaker plays.
   - **Mono-sum cancellation**: power of (L + R) / 2 over mean channel power, render minus original.
   - **Low end**: correlation of the two mono low ends below 120 Hz at the measured lag (the
     identity of the bass), the level change there, and the L/R correlation of each.
   - **Artifact flags with timestamps** (`stage.guard.artifacts`): clipping runs (3 or more
     samples at -0.01 dBFS), octave-band dropouts (15 dB below the original for 60 ms, only where
     the band is within 45 dB of the frame's loudest), pre-echo (energy in the 20 ms before the
     original's high-band onsets, 8 dB above the original's ratio and above -30 dB relative to the
     transient: the backward-masking window), and musical noise (isolated time-frequency peaks
     above 1 kHz, three times the original's density and at least 40 per second).
   - **Verdict**: `fail` (true peak above -0.1 dBTP, clipping, loudness off by 2 LU, a 6 dB band,
     bass correlation below 0.8, more than 5 ms out of time), `review` (anything past its review
     threshold, any other artifact flag), else `pass`, with one plain sentence per reason.
   Every threshold is in `configs/thresholds/guard.json` with its reason. The Space bundle copies
   `configs/` into the package (`stage.config`), so the Space reads the same files.
3. **start = "auto"** is the default everywhere (service, pipeline, Gradio form, web app): the
   start of the loudest window of the requested length, by the mean K-weighted energy over 100 ms
   steps streamed from the file (`stage.analysis.excerpt`). The chosen start, its loudness and
   `start_mode` are in run.json.
4. The Gradio form uses text boxes for Start and Length. A `gr.Number` shows 0 when empty, which
   reads as a choice and could send a 0-second length; the form now has exactly one Start and one
   Length field, empty means the default, and `stage.service.parse_seconds` refuses 0 (and
   anything outside 1 to 120 s or not a number) with a message, whatever the client.

## Sources

- ESTABLISHED: ITU-R BS.1770-4 (2015), "Algorithms to measure audio programme loudness and
  true-peak audio level": K-weighting tables, gating, Annex 2 true peak. EBU Tech 3341 (2016) for
  the 3 s short-term window, EBU R128 (2020) for the +/-1 LU tolerance. The 48 kHz coefficients in
  `loudness.py` are the standard's; the multi-rate parameters are from
  github.com/BrechtDeMan/loudness.py, read through pyloudnorm's `iirfilter.py`, which ships them.
- ESTABLISHED (as a practice, not a standard): three consecutive full-scale samples as a clipped
  run, as used in mastering meters.
- SPECULATIVE: the pre-echo, dropout and musical-noise detectors and their thresholds are
  engineering proxies chosen here, not validated perceptual models. They are tuned so that an
  identical render gives no flags and the synthetic defects in `tests/unit/test_guard_report.py`
  are each found. Their purpose is to point a listener at a timestamp.

## Measured

On a generated 10 s kick, hats, chord test signal rendered with v1 (`max`): verdict `review`;
timbre deviation 3.6 dB at 3.15 kHz; mono high band -2.1 dB; 18 pre-echo flags, one on every hat
(the 2048-sample STFT frame of the v1 renderer spreads each transient over about 46 ms); musical
noise over the whole clip (312 isolated peaks per second against 82 in the original, from the
random-phase ambient path). Bass correlation 0.999. These are the artifacts the owner heard,
now with numbers; Phase 1 and 2B are measured against them.

## Consequences

- Every run has a verdict the web app can show honestly.
- The guard costs about 1.4 s per 10 s of audio on the build machine; it runs on the CPU after
  the GPU-bound separation.
- run.json has a sixth stage and the `guard` and `auto_start` fields (schema updated).

## Alternatives considered

RMS matching only (the old `levels`): it ignores the ear's frequency weighting, so a bass-heavy
render reads louder than it sounds. A full perceptual model (PEAQ, ITU-R BS.1387): far heavier,
and designed for codecs, not for spatial renders whose differences are intended.
