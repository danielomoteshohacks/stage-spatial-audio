# 0014. The record's tone and bass: zero-phase bypass, timbre matcher, loudness match

- Status: accepted
- Date: 2026-11-24

## Context

The owner's rule: the bass stays the bass, and the render must not change the tone of the
record. Binaural rendering colours the long-term spectrum (each direction's head response,
room reflections, the comb of two loudspeakers summing at each ear), and v1's RMS levelling
moved the bass with everything else.

## Decision

1. **Bass bypass.** Below 120 Hz the original passes untouched. The split is a zero-phase
   Linkwitz-Riley: a 4th-order Butterworth low-pass run forward and backward (Linkwitz-Riley
   magnitude, 48 dB per octave), with the high band defined as the remainder, so the bands sum to
   the input exactly (1e-17). The first version used the 2nd-order section (24 dB per octave);
   reverberated upper band below 100 Hz then lowered the bass's correlation with the record to
   0.98 on broadband noise; the steeper slope keeps it above 0.99. Frequency and order are
   parameters (`stage.spatial.neutral`).
2. **Diffuse-field EQ** of the head filters (decision 0012).
3. **Timbre matcher.** 1/3-octave long-term spectra of the rendered upper band and the original
   upper band from 125 Hz to 16 kHz; correction limited to +/-12 dB and to shape only (the
   energy-weighted mean is removed); one minimum-phase FIR applied identically to both ears, so
   every interaural difference is kept; faded to 0 dB an octave below 125 Hz.
4. **Loudness.** Only the upper band is scaled, by bisection on BS.1770 loudness, so the whole
   render matches the original within 0.02 LU while the bass is not touched. The pipeline no
   longer RMS-matches v2 renders.

## Measured (generated 30 s test track, guard report)

| Profile | Verdict | Timbre max dev. | Bass correlation | Artifact flags |
|---|---|---|---|---|
| v1 `max` | review | 5.4 dB at 10 kHz | 0.9996 | 38 (30 pre-echo, 8 musical noise) |
| v2 studio | pass | 2.3 dB | 1.0000 | 0 |
| v2 living room | review | 3.5 dB at 125 Hz | 0.9997 | 0 |
| v2 car | review | 5.8 dB at 8 kHz | 0.9997 | 0 |
| v2 club | pass | 2.8 dB | 0.9998 | 0 |
| v2 concert hall | pass | 2.4 dB | 0.9998 | 0 |
| v2 cinema | pass | 2.0 dB | 0.9998 | 0 |

Alignment is 0.02 ms for every v2 space; loudness differs by under 0.01 LU.

## The guard itself was fixed on the way

v2 exposed two faults in the Phase 0 guard. Its alignment check cross-correlated broadband
waveforms, which on a reverberant render locked onto a half bass period (11 to 25 ms, with the
bass then judged "inverted" at that lag). It now aligns on transients (onset envelopes, then a
1 to 8 kHz refinement that takes the earliest strong peak, the direct sound) and judges the
bass within its own small lag window. Its pre-echo detector counted the previous hit's reverb
tail as pre-echo; it now requires energy that rises into the transient. The downmix review
threshold moved from 2 to 3 dB, which is what decorrelation alone costs a mono fold.

## Sources

ESTABLISHED: Linkwitz 1976 (the crossover alignment); the Butterworth power-complementarity is a
textbook identity; Knapp and Carter 1976 for generalised cross-correlation (used and then
replaced, see above). SPECULATIVE: that a 1/3-octave, shape-only match restores the perceived
tone without weakening localisation; the blind test decides.
