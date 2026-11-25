# 0030. How v1, v2 and v3 are compared, and the blind test with a reference slot

- Status: accepted
- Date: 2026-11-25

## Decision

**Two benchmarks, because one of them cannot judge v3.**

1. `scripts/benchmark_groundtruth.py` (ESTABLISHED method, decision 0022): generated songs of 15
   parts with known 3D positions, folded to stereo. The engine sees only the fold and the stems it
   is given; the score is where the render's direct energy goes compared with where the truth's
   goes (sector shares, earth mover's distance of the direction-energy map in degrees) and the
   per-part angular error. Two separators are used: the true parts (an upper bound, isolating
   the renderer) and the true four stems split by the model-free cascade levels (what today's
   four-stem separators plus our DSP give). Neural levels are scored by running the same script
   on the Space's GPU, which has not happened.
2. `scripts/benchmark_spatial.py`: the v2-era proxies (IACC, ITD and ILD spread, lateral energy,
   DRR, coherence) plus the guard. v3 columns were added. These proxies measure interaural
   decorrelation. They are kept so v1, v2 and v3 sit in one table and so nobody has to take it on
   trust that v3 "looks better on the old numbers": it does not.

**Reading of the results** (full tables in README.md; raw rows in `docs/benchmarks/`):

| Target (decision 0027) | v3, true parts | v3, four stems | Verdict |
|---|---|---|---|
| Outside-front share at least 3 times v2's | 3.2 times (45.2% against 14.1%) | 2.1 times (30.1%) | met with perfect parts, not with four stems |
| Direction map within 15 degrees of the truth | 12.3 | 6.6 | met |
| Per-part angular error at most 20 degrees | 16.4 | 67.2 | met with perfect parts, **failed** with four stems |
| Timbre deviation at most 1.5 dB | 0.78 | 0.64 | met |
| Guard pass | 2 of 2 | 1 of 2 (one flag) | partly |
| Render real-time factor under 0.2 (30 s, 4 vCPU) | 0.05 | 0.05 | met (1.4 to 1.5 s without separation) |
| First sound under 3 s after the first chunk is separated | 1.9 s model-free | | met on the model-free path; with neural levels **not measured** |

The 20 degrees is SPECULATIVE: it is set near the localisation blur reported for non-individual
head-related filters (Wenzel et al. 1993; Middlebrooks 1999), not derived. The 3 times target is
the brief's, and decision 0022 notes that protected parts cap it.

**v3 does worse than v2 on the v2-era proxies**: IACC 1.00 against 0.89 (Lite) and 0.83 (living
room), lateral energy 0.000 against 0.118. Why, in order of confidence: (a) a dry source straight
ahead is identical in both ears, so centred content has IACC 1 by physics, and the generated songs
centre the vocal, chords and drums; (b) v2 bought its decorrelation from a room on every object,
which decision 0022 found to be most of what it did; (c) v3's side content depends on the
separation, and the model-free split finds little to the sides in a centre-heavy mix. None of this
is evidence that v3 sounds worse, and none of it is evidence that it sounds better.

**The blind test** (`web/src/components/BlindTest.svelte`, `web/src/lib/blindtest.ts`): the
original, the v3 render and an optional reference are three or four letters in a rotating order
(every condition lands on every letter equally often), matched in loudness by turning the louder
ones down to the quietest, looping over the span all letters share so switching is sample-locked,
with a 30 ms cross-fade. The listener ranks them and picks "most outside my head" and "most
natural". Trials stay in the browser and export as CSV (trial, time, track, the order, the ranking,
the two picks, the gains, the reference file's name). Nothing is sent anywhere.

**The reference slot** exists because the useful comparison is with what listeners already know.
SoundStage does not ship, produce or imitate any commercial format; the listener loads a headphone
rendering of the same song that they have the right to use, for example an Atmos-style binaural
version of a track they own, and it is judged blind like the rest. The file is decoded locally.
Start-point alignment is the listener's responsibility and the loop span is the shortest letter.
Because the reference is not produced by this project, a result against it says something about
that file and that listener only. **The project makes no claim of matching or beating any
commercial format;** a claim needs a published sample size, an interval and the raw CSV.

## Not done

No listener has used the test: the owner runs it. A sample-size rule is not fixed here: 20 listeners
and five songs would give an interval of about plus or minus 20 points on a preference rate, which
is enough to see a large effect and nothing smaller (SPECULATIVE; a power calculation belongs with
the owner's plan).
