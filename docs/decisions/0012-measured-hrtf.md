# 0012. Measured ears: the SADIE II KU100 pack, interpolated without combing

- Status: accepted
- Date: 2026-11-24

## Context

The owner heard v1 stay inside the head and confuse front and back. v1's head is a sphere with a
toy pinna (`stage.render.headmodel`, `pinna`); it has the right interaural time and level
differences but none of the spectral detail a real outer ear, head and torso put on a sound,
which is what places it outside the head and in front rather than behind. v1 also summed the
complex filters of neighbouring pan sectors, which combs the far ear (decision 0010).

## Decision

1. **Data.** SADIE II (The Audio Lab, University of York), subject D1, a Neumann KU100 dummy
   head, 8802 measured directions at 48 kHz, 256-tap FIRs, already diffuse-field equalised by
   the authors. Licence checked in two places: the Zenodo record 10.5281/zenodo.12092466
   (version 2-2) lists Apache-2.0, and the SOFA file's own `License` attribute reads "Copyright
   2018, University of York, Licensed under the Apache License, Version 2.0". Attribution:
   Armstrong, Thresh, Murphy and Kearney, "A Perceptual Evaluation of Individual and
   Non-Individual HRTFs: A Case Study of the SADIE II Database", Applied Sciences 8(11), 2029,
   2018. The KU100 is a standard non-individual reference head; no single head fits everyone.
2. **Build on GitHub Actions** (`.github/workflows/hrtf-pack.yml`, `tools/hrtf-pack`). The runner
   downloads `D1.zip` from Zenodo, checks its md5 against the record, refuses anything that is
   not Apache-2.0, reads SOFA with h5py (BSD-3-Clause; no SOFA-specific library needed) and
   publishes `sadie2-d1-ku100.npz` (1.87 MB) and `sadie2-d1-brir48k.npz` (2.5 MB) with
   `manifest.json` as assets of release `hrtf-pack-v1`. Nothing large is committed. The Space
   downloads the pack at start-up (`space/app.py`, checked against the SHA-256 in
   `stage.spatial.hrtf`) and falls back to the analytic head until it arrives.
3. **Representation.** Each direction is stored as a log magnitude per ear (float16) plus one ITD
   (onset at -20 dB on 3 kHz low-passed, 8x upsampled responses; Andreopoulou and Katz 2017).
   Filters are rebuilt as minimum phase (homomorphic method) plus a fractional delay. Kulkarni,
   Isabelle and Colburn (1999) found the HRTF excess phase inaudible once the ITD is kept.
4. **Resampling and smoothing.** The KU100 grid is rings at 1 degree azimuth steps: 4070 points
   lie within 0.5 degree of another, and neighbouring far-ear measurements differ by up to 9 dB,
   so linear interpolation across that grid jumped 37 dB per degree in a 1/3-octave band. The
   builder resamples onto a uniform 4000-point Fibonacci grid by Gaussian kernel regression,
   wider for the far ear (the near ear dominates spectral localisation, Hofman and Van Opstal
   2003) and twice as wide above 8 kHz (where dummy-head detail matches listeners least,
   Middlebrooks 1999). It picks the smallest kernel that meets the continuity target. Chosen:
   4 degrees for the near ear, 10 for the far ear, ITD 2 degrees.
5. **Interpolation.** Barycentric weights in the spherical Delaunay triangle (Qhull facets of the
   unit vectors) blend the log magnitudes; the ITD is blended separately. No complex responses
   with different delays are ever summed, so a moving source cannot comb.
6. **Diffuse-field EQ.** The power average over the sphere (area-weighted) is 1/3-octave smoothed
   and divided out of both ears equally (decision 0014).

## Measured

| Measure | Value |
|---|---|
| Worst 1/3-octave change along azimuth sweeps (elevations -30 to 60, 0.25 degree steps) | **0.47 dB per degree** (target 0.5), 16 kHz band behind the head |
| Same along elevation sweeps (azimuths 0 to 180) | 1.59 dB per degree, 8 kHz band at azimuth 90, elevation -10 |
| Analytic fallback, azimuth / elevation | 0.46 / 0.50 dB per degree |
| ITD range of the pack | -0.66 to +0.71 ms |
| Measured diffuse-field interaural coherence (KU100) | 0.81 at 188 Hz, 0.28 at 375 Hz, below 0.1 from 560 Hz |

The 0.5 dB per degree target is met for azimuth movement, which is how the motion of decision
0018 moves sources. It is not met for elevation: the pinna notch that sweeps through 6 to 10 kHz
as a source rises is the elevation cue itself, and smoothing it below 0.5 dB per degree would
erase height. That trade is made on purpose and is measured in the pack's manifest.

## Sources

ESTABLISHED (read): the SADIE II Zenodo record metadata and the SOFA file attributes (licence,
processing history); Allen and Berkley 1979 and Oppenheim and Schafer for the methods named.
ESTABLISHED (from the cited papers' abstracts and results as known to the author, not re-read
in this session): Kulkarni et al. 1999; Andreopoulou and Katz 2017; Hofman and Van Opstal 2003;
Middlebrooks 1999. SPECULATIVE: that 4/10 degree smoothing is perceptually transparent; it is a
measured continuity choice, to be confirmed by the listening test.

## Patents

No patent risk found for HRTF interpolation by barycentric weights or minimum-phase plus ITD
representation; both are textbook methods in the open literature for decades.

## Consequences

The default engine uses measured ears. Front/back and externalisation should improve; the
listening test decides. A listener whose ears differ much from a KU100 may still hear front/back
reversals; head tracking (decision 0008) is the known remedy.
