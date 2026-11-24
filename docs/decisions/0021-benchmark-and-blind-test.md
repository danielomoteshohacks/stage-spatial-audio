# 0021. Proof: an objective spatial benchmark, and a blind test that decides

- Status: accepted
- Date: 2026-11-24

## Decision

- `scripts/benchmark_spatial.py` renders five generated multitrack songs (stage.testsongs:
  synthesised drums, bass, chords, a formant voice and ambience; deterministic, no recordings),
  30 s each from 20 s in, with v1 Lite (`max`), v2 Lite (studio), and the v2 stems scene (Pop
  template, motion 0.5) in the studio and in the living room, and reports externalisation
  proxies (IACC 500 Hz to 4 kHz within +/-1 ms; ILD and ITD spread over time-frequency tiles;
  a DRR estimate from a 5 ms least-squares fit to the original), envelopment proxies (lateral
  energy of the side signal 250 Hz to 4 kHz; interaural coherence in 100 ms frames, mean and
  spread) and fidelity (timbre deviation, artifact flags, bass correlation, loudness difference,
  render time). True stems are used for the scene so the benchmark measures rendering; the
  separator has its own evaluation (decision 0015).
- The web app's blind test (decision 0020) is how a perceptual claim will be made: random order,
  loudness-matched, ranking plus "most outside my head" and "most natural", exported as CSV.
- The README never claims to beat a commercial format; it reports these numbers and, later, the
  blind-test results with their sample size.

## Results (5 songs, means)

| Metric | Better | v1 Lite | v2 Lite | v2 stems, studio | v2 stems, living room |
|---|---|---|---|---|---|
| IACC | lower | 0.956 | 0.887 | 0.973 | **0.830** |
| ILD spread (dB) | higher | 7.19 | 5.96 | 6.46 | **7.60** |
| ITD spread (us) | higher | 96.5 | 184 | 103 | **273** |
| DRR estimate (dB) | lower: more room | 7.19 | 15.4 | 7.53 | **3.09** |
| Lateral energy | higher | 0.0068 | **0.118** | 0.0094 | 0.0804 |
| Coherence, mean | lower | 0.949 | **0.419** | 0.965 | 0.759 |
| Coherence, spread over time | higher | 0.033 | **0.212** | 0.072 | 0.130 |
| Timbre deviation (dB) | lower | 4.45 | 1.20 | **0.95** | 2.39 |
| Artifact flags | lower | 18.2 | **0** | **0** | **0** |
| Bass correlation below 120 Hz | higher | 0.999 | **1.000** | **1.000** | **1.000** |
| Loudness difference (LU) | lower | 0.046 | **0** | **0** | **0** |
| Render time, 30 s (s) | lower | **1.76** | 3.99 | 8.77 | 8.81 |
| Guard verdicts | | 5 review | 5 pass | 5 pass | 5 pass |

## Where v2 does not beat v1, and why

- **Render time.** v2 does far more (measured head filters, rooms, a decomposition per stem,
  motion); it stays inside the Phase 4 targets.
- **v2 stems in the studio, spatial proxies.** The studio is fitted to a measured treated room
  (DRR 11 dB) and the scene keeps centred sounds centred (vocal, kick, snare, bass), so on these
  centre-heavy test songs it is about as compact as v1. That space is the dry, faithful choice by
  design; the living room, now the default, is the enveloping one.
- **v2 Lite, ILD spread and DRR estimate.** v2 Lite puts the mix on a +/-30 degree stage
  (where the mix was made) instead of v1's widening toward +/-80 degrees, so level differences
  spread less; and v1's random-phase ambient path, which the guard flags as musical noise, reads
  as "room" to the least-squares fit. v2 Lite's envelopment comes from its bed instead (lateral
  energy 17 times v1's, coherence 0.42 against 0.95).
- **Timbre in the living room** (2.4 dB) is above the studio's 0.95 dB because a real room colours
  the sound; it is inside the guard's 3 dB review threshold on every song.

These are proxies on synthetic music. They say v2 is more spacious and cleaner by the standard
measures; whether it sounds better is for the blind test.
