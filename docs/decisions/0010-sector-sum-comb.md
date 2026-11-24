# 0010. Neighbouring sectors comb-filter the far ear

- Status: accepted as a measurement. No renderer change is decided here; the fix is open (below).
- Date: 2026-11-19

## Context

0006 noted that adding the complex filters of neighbouring sectors, whose delays differ, "can
cancel a little at high frequencies; not yet measured". This record measures it.

A source at stereo angle theta is shared over neighbouring sectors by Gaussian weights
(sigma 2.5 degrees, spacing 5 degrees). Each sector is rendered at its own widened azimuth, with
its own Woodworth delay in the far ear. At each ear the copies add as complex numbers. Two copies
whose far-ear delays differ by `dtau` cancel at `f = 1 / (2 dtau)` and its odd multiples.

The near ear has no comb: every sector on the source's side has a zero near-ear delay.

## Method

`scripts/measure_sector_sum.py` computes, at the renderer's own STFT bins (n_fft 2048, 44.1 kHz,
21.5 Hz per bin), the primary-path response of each ear:

    H_sum(f) = sum_k w_k(theta) F_k(f)

It is built from the renderer's own functions (`direct_filters`, `sector_weights`,
`_split_gains`). The comb is reported as `20 log10 |H_sum / H_ref|`. `H_ref` is the same ear filter
at the source's exact widened azimuth, the single-filter reference used in 0006. Dividing by it
removes the head shadow, which is intended, and leaves only what the sector sum adds.

Two summaries are given:

- **Per bin.** Can be very deep where two equal copies cancel exactly.
- **Per 1/3-octave band** (100 Hz to 16 kHz). Given per ear, and as both ears' power summed. The
  summed figure is what the guard's timbre check sees on a whole render.

`--verify` renders amplitude-panned white noise through `render_stereo` and compares the measured
ear-to-source ratio with `H_sum`. The largest difference from 100 Hz to 16 kHz was 0.01 dB at
theta 2.5 and 0.03 dB at theta 27.5, so the numbers describe the real chain. The test checks this
at three positions to within 0.1 dB.

All values are single deterministic measurements of the signal path. There is no sampling, so
there is no interval. They are not listening results.

## Results

### V0 (default renderer), beta 2.0

Worst dip of `H_sum / H_ref`. The far ear is L, since every position is right of centre; the
left half is the mirror image (tested).

| theta (deg) | position | per bin | per bin, 10-20 kHz | 1/3 oct, one ear | 1/3 oct, both ears |
|---|---|---|---|---|---|
| 0.0 | centre | -1.56 dB at 5.6 kHz | -1.52 at 17.0 kHz | -1.50 (5 kHz) | -1.50 (5 kHz) |
| 2.5 | between | -17.15 at 5.6 kHz | -16.48 at 17.0 kHz | -12.79 (5 kHz) | -2.09 (5 kHz) |
| 5.0 | centre | -4.90 at 5.7 kHz | -4.81 at 17.2 kHz | -4.63 (6.3 kHz) | -0.91 (5 kHz) |
| 7.5 | between | -18.17 at 5.9 kHz | -16.90 at 17.8 kHz | -14.28 (6.3 kHz) | -0.95 (5 kHz) |
| 12.5 | between | -18.11 at 6.4 kHz | -16.02 at 19.4 kHz | -16.05 (6.3 kHz) | -0.44 (6.3 kHz) |
| 15.0 | centre | -4.91 at 6.7 kHz | -4.39 at 19.9 kHz | -4.79 (6.3 kHz) | -0.22 (5 kHz) |
| 17.5 | between | -18.89 at 7.3 kHz | -7.08 at 20.0 kHz | -13.90 (8 kHz) | -0.22 (6.3 kHz) |
| 22.5 | between | -20.71 at 8.6 kHz | -11.77 at 10.0 kHz | -15.43 (8 kHz) | -0.13 (5 kHz) |
| 25.0 | centre | -4.82 at 9.2 kHz | -4.69 at 10.0 kHz | -4.60 (10 kHz) | -0.07 (5 kHz) |
| 27.5 | between | -24.61 at 10.4 kHz | -24.61 at 10.4 kHz | -17.82 (10 kHz) | -0.08 (6.3 kHz) |
| 30.0 | centre (edge) | -2.57 at 10.5 kHz | -2.57 at 10.5 kHz | -2.51 (10 kHz) | -0.08 (7.9 kHz) |

Sweep from 0 to 30 degrees in 0.25 degree steps:

- **Worst single-bin dip: -53.55 dB at 8635 Hz**, far ear, theta 22.75 degrees.
- Worst single-bin dip in the top octave (10 to 20 kHz): -29.58 dB at 19423 Hz, theta 13 degrees.
- Worst 1/3-octave dip in one ear: -19.68 dB in the 6.3 kHz band, theta 12.75 degrees.
- Worst 1/3-octave dip with both ears' power summed: -2.11 dB in the 5 kHz band, theta 2.25 degrees.

### Other widths and the "max" profile (sweep worst cases)

| | per bin | top octave, per bin | 1/3 oct, one ear | 1/3 oct, both ears |
|---|---|---|---|---|
| V0, beta 1.0 | -35.05 at 11240 Hz (theta 2.75) | same | -20.12 (12.5 kHz, theta 22.75) | -2.51 (10 kHz, theta 2.25) |
| V0, beta 2.0 | -53.55 at 8635 Hz (theta 22.75) | -29.58 at 19423 Hz (theta 13) | -19.68 (6.3 kHz, theta 12.75) | -2.11 (5 kHz, theta 2.25) |
| V0, beta 2.4 | -49.48 at 17183 Hz (theta 13) | same | -19.30 (5 kHz, theta 7.75) | -1.98 (5 kHz, theta 2.25) |
| max (V4b direct path), beta 2.0 | -38.56 at 8506 Hz (theta 17.75) | -36.78 at 18562 Hz (theta 8.25) | -20.78 (12.5 kHz, theta 27.75) | -2.08 (5 kHz, theta 2.25) |

For "max", only the direct path is measured. The early reflections are a separate path and are
not part of the sector sum.

### What the numbers say

- **Yes, neighbouring sectors comb-filter, and not only in the top octave.**
  - The first notch is at `1 / (2 dtau)` of the two sectors that straddle the source. At beta 2.0
    that is 5.6 kHz near the centre, rising to 10.4 kHz at the edge, because the warp compresses
    the outer sectors' azimuths and the Woodworth delay flattens towards the side.
  - The top octave holds the third harmonic of that notch (17 to 20 kHz) for sources within
    about 15 degrees of the centre, and the first notch for sources past about 22 degrees.
  - At beta 1.0 the first notch is at 11 to 13 kHz for every position, so all of it is in the
    top octave.
- **The depth depends on where the source sits between sector centres.**
  - Halfway between two centres the two copies have equal weight, so the far ear notches by 17
    to 25 dB per bin (13 to 18 dB per 1/3 octave).
  - On a sector centre the neighbours still carry about 11 percent of the weight each, and the
    notch is about 5 dB.
  - A source that moves in pan, or a bin whose estimated angle fluctuates, therefore sweeps a
    notch of changing depth through the far ear's treble.
- **Summed over both ears, the colour change is about 2 dB at most.** It happens near the centre,
  where the two ears are equally loud. Past about 10 degrees the far ear is already 10 to 20 dB
  down from head shadow, so its notch hardly changes the total. A 2.1 dB dip at 5 kHz on its own
  exceeds the guard's 1.5 dB per-band timbre bound for a source near the centre.
- **Per ear, the comb is not small.** It distorts the far ear's spectrum, and so the high-frequency
  ILD, by up to about 20 dB in a band. Whether that is audible as colour, as image shift or not at
  all is a listening question this record does not answer.

### First guard run on the default renderer

A synthetic pink mix, 8 s: sources at 0, +15 and -25 degrees plus a decorrelated pair, at
beta 2.0. Rendered with `scripts/render_clip.py --guard`; the mix is written to a temporary folder
and not committed.

| Check | Result |
|---|---|
| Alignment | 0 samples, pass |
| Loudness | 0.00 dB after matching, pass |
| Timbre | **fail**, max 2.37 dB in the 6.3 kHz band. Failing bands: 2.5 to 8 kHz and 16 kHz |
| Low end | +0.50 dB; L/R correlation 0.770 against 0.383 in the original. Not gated |

This agrees with 0007's V0 P5 baseline of 2.45 dB at 4 kHz, which was measured on a different mix
and in octaves. The guard number contains both the intended head shadow and this comb; this
record separates the comb's share.

## Decision

- Record the comb as a known property of the Lite sector chain.
- Keep `scripts/measure_sector_sum.py` as the measurement to repeat after any change to the
  sectors, the warp or the ear filters.
- Do not change the renderer in this task.

## Consequences

- The comb adds to the head shadow's share of the guard's timbre deviation. For a single source
  it is up to 2.1 dB in a band near the centre. Its share on real, multi-source material has not
  been measured.
- Candidate fixes, to be registered with a gate before they are tried:
  1. **Per-bin magnitude and delay interpolation.** Interpolate magnitude and delay at the bin's
     own widened azimuth instead of summing complex sector responses. The
     `AzimuthFilterBank` table of 0007 H17 already interpolates this way, and H17 measured at most
     0.017 dB interpolation error. This removes the comb by construction. The cost is a table
     lookup per bin instead of a 13-term sum.
  2. **Align the far-ear delays across the sectors that share a bin** before summing. Close to
     option 1, but it keeps the sector structure the rotation design (0008) relies on.
  3. **Narrower Gaussians.** These shrink the cancelling weight at a sector centre but not
     halfway between centres, where it matters. Not recommended.
- Any fix changes V0's output, so 0007's measurements and the blind test baseline would have to
  be repeated.

## Alternatives considered

- **Measuring through `render_stereo` alone.** Slower and noisier, and it mixes in the analysis
  smoothing. It is used only to verify the closed-form numbers (`--verify`).
- **Reporting only the single-bin minimum.** It can be arbitrarily deep at an exact cancellation,
  so the 1/3-octave figures are reported alongside it.
