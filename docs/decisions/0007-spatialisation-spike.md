# 0007. Spatialisation spike: externalisation and space in the Lite tier

- Status: proposed (research spike; gates below were written before the profiles were implemented)
- Date: 2026-11-18

## Context

First real listening test (stereo pop track, beta 2.0, headphones, one listener): the Lite render is
wider at the sides but collapses toward the back and inside the head, with no height and no sense
of a space around the listener. The chain is Woodworth ITD plus Brown-Duda head shadow only.

That result is what the literature predicts for this chain:

- A spherical head gives identical ITD and ILD for azimuth `az` and `180 - az`. In Brown and Duda's
  words (1998, Fig. 3 caption), "it is elevation, not azimuth, that distinguishes front from back".
  Our model has no cue that separates the front from the back.
- Anechoic, uncompensated head models externalise weakly "since they lack the distance cues
  derived from room reverberation" (Brown and Duda 1998, Sec. V). Begault, Wenzel and Anderson
  (2001) found significant effects of head tracking, reverberation and individualised HRTFs on
  reversal rate and externalisation.
- Head movement matters a lot. Brimijoin, Boyd and Akeroyd (2013) found virtual sounds fixed to
  the world were externalised 65 percent of the time, against 20 percent for sounds fixed to the head.

The spike tests closed-form additions that stay in Lite: no neural network, no measured or
downloaded HRTF data, and real-time capable. `render_stereo` keeps its default behaviour; every
addition sits behind a named profile.

### What was verified, and how

| Fact used | Source | How it was checked |
|---|---|---|
| Pinna events: `tau_n = A_n cos(theta/2) sin(D_n (90 - phi)) + B_n`, valid for -90 <= theta, phi <= 90 | Brown and Duda 1998, Eq. (8) | Read off a rendered page of the PDF |
| Table I: rho = 0.5, -1, 0.5, -0.25, 0.25; A = 1, 5, 5, 5, 5; B = 2, 4, 7, 11, 13; D (PB and NH) = 1, 0.5, 0.5, 0.5, 0.5; D (RD) = 0.85, 0.35, 0.35, 0.35, 0.35 (events n = 2 to 6, delays in samples at 44.1 kHz) | Brown and Duda 1998, Table I | Read off a rendered page of the PDF |
| The pinna model was fitted to the frontal half space only, and front/back was not addressed | Brown and Duda 1998, Secs. II and VI: "Our investigation was limited to the frontal half space, and we did not address front/back discrimination problems" | Text of the PDF |
| Directional bands (1/3-octave noise, median plane): front ("v", presence) peaks near 300 to 500 Hz and 3.15 kHz; above ("o") near 8 kHz; behind ("h") near 1 kHz (about 90 percent of answers) and 10 to 12.5 kHz | Blauert, *Raeumliches Hoeren* (1974) figure, as reproduced by E. Sengpiel, UdK Berlin (1994), "Die Richtungswahrnehmung nicht nur in der Medianebene". Original paper: Blauert, Acustica 22 (1969/70) | Values read from the reproduced figure. **The original paper was not seen.** |
| Directional bands vary between people; no band common to all subjects was found | Itoh, Iida et al., Applied Acoustics 2007 | Abstract via search only |
| Head-tracking latency: mean detection threshold 107.6 ms (SD 30.4, 95 percent CI 101.3 to 114 ms), lowest 52 ms, n = 22; Brungart et al. (2005) lowest 60 ms, Yairi et al. (2006) lowest 75 ms | Lindau, DAGA 2009 | Text of the PDF |
| DRR discrimination thresholds of 5 to 6 dB, from 0 to 20 dB DRR, n = 6; Larsen et al. later found 2 to 3 dB at 0 and 10 dB | Zahorik, JASA 112(5), 2002; Larsen et al. (PMC2677334) | Abstracts via search |
| Normalised echo density: the fraction of samples outside one local standard deviation, divided by erfc(1/sqrt 2), in a window of about 20 ms; 1 means Gaussian-like | Abel and Huang, AES 121st Convention, 2006 | Secondary description via search; the formula is reproduced in arXiv 2404.00082 |
| Frequency-dependent interaural coherence of an FDN late field, set by linear filters outside the loop | Menzer and Faller, AES 2009; Menzer, EPFL thesis 2010 | Abstracts via search |

The following were cited from memory and **not re-read** in this spike, so treat them as to-check:

- Allen and Berkley (1979), image-source method.
- Jot and Chaigne (1991), FDN.
- Schroeder (1965), backward integration.
- ISO 3382-1, IACC within +/-1 ms.
- Cook et al. (1955), diffuse-field coherence `sin(kd)/(kd)`.
- Brungart and Rabinowitz (1999) and Duda and Martens (1998), near-field ILD.

### Patent flags (CLAUDE.md: "flag any doubt")

- The patent search for the pinna formula returned **US 9602927** ("Speaker and room virtualization
  using headphones"). Its pinna section appears to use the same `A cos(theta/2) sin(D(90 - phi)) + B`
  form inside a headphone virtualiser. Its claims could not be read (scanned images). The model
  itself is a 1998 journal paper, and we implement it from the paper, not from the patent. **A
  review of the claims is needed before shipping.**
- The search for "directional bands" returned US 8005245 ("Sound image localization apparatus")
  and US 11418901 / US 11902770 ("System and method for providing three-dimensional immersive
  sound"). They were not read. Using directional bands as a steering EQ may overlap with them.
  **A review is needed before shipping.**
- Head-tracked rotation of a set of virtual sources is a crowded patent field. See 0008.

## Hypotheses

Tags: **ESTABLISHED** means the mechanism is in the cited literature. **SPECULATIVE** means it is
our own extension, an unverified extrapolation, or the source is too thin. Every gate below is an
objective proxy. It shows that the cue is present in the signal; it does not show that anyone hears
it. **The blind listening test (`scripts/make_abx.py`) decides.** This record makes no perceptual claim.

### H11. Front-arc limit on the widen warp (profile V1)

- **Mechanism:** The warp asymptote drops from 80 to 60 degrees (`alpha = 60 tanh(beta theta / 60)`).
  The slope at the centre is unchanged, so the centre image keeps its width and only the edges are
  compressed.
- **Tag:**
  - ESTABLISHED: the cone of confusion (the mirror symmetry of our model).
  - SPECULATIVE: that limiting width reduces the collapse toward the back. The cones of confusion
    exist at every azimuth, and no source gives a "flip angle". At beta 2.0 the V0 edge sector
    already renders at only 50.8 degrees, and V1 moves it to 45.7 degrees.
  - The brief tagged this ESTABLISHED; we do not, for the reasons above.
- **Proxies:**
  - (a) every rendered sector azimuth is at most 60 degrees for any beta;
  - (b) the broadband ILD of a hard-panned pink source keeps at least 80 percent of V0's
    (V0 measured 3.04 dB at beta 2.0).

### H12. Structural pinna model (profile V2)

- **Mechanism:**
  - Six pinna events per ear, from Brown and Duda's Eq. (8) and Table I, with the PB/NH column
    for D and event 1 the direct path (rho 1, tau 0).
  - Each event is an exact fractional delay in the frequency domain, where Brown and Duda used
    linear interpolation between taps.
  - Angles are interaural-polar: lateral `theta = asin(sin az cos el)` and polar
    `phi = atan2(sin el, cos az cos el)`, wrapped to [-90, 270) so that the seam is directly
    below the listener.
  - A diffuse-field equalisation divides out the pinna's average power response over the sphere,
    so the average colour is removed and the directional differences remain.
- **Tag:**
  - ESTABLISHED for elevation in the frontal half space. Brown and Duda's matching tests, with
    three subjects, show perceived elevation following the model.
  - SPECULATIVE for front/back. The formula is used outside its fitted range (phi > 90 degrees)
    to produce a rear response.
- **Proxies:**
  - (a) Elevation: at az 0, the deepest notch between 5 and 14 kHz rises monotonically in
    frequency over el = -30, -15, 0, 15, 30, 45 degrees. Measured pinna notches rise with
    elevation (Spagnol et al. 2013 found this in CIPIC data).
  - (b) Front-rear tilt `dT = T(az 0) - T(az 180)` is at least +1.0 dB, where
    T = mean ear level in the front bands (400 Hz, 3.15 kHz) minus mean in the rear bands
    (1 kHz, 11.2 kHz). The sign must agree with Blauert. A negative value means the extrapolated
    rear cue contradicts the directional bands.
  - (c) Timbre, as in P5.

### H13. Directional-band steering EQ (profile V3)

- **Mechanism:**
  - A gentle per-direction EQ built from Blauert's bands. Each band is a log-frequency Gaussian
    with sigma = 1/3 octave.
  - Frontness `c = cos az cos el`. For c > 0, the front bands (3.15 kHz at depth g, 400 Hz at g/2)
    are raised and the rear bands (1 kHz and 11.2 kHz at depth g) are lowered, both by c times
    the depth. For c < 0 the signs swap.
  - For el > 0, sin(el) times g raises 8 kHz (used by ceiling reflections).
  - g = 1.5 dB, so no band moves by more than 1.5 dB, the H2 timbre bound.
- **Tag:**
  - ESTABLISHED: the psychoacoustics, for 1/3-octave noise in the median plane.
  - SPECULATIVE: the use as a cheap steering layer on broadband music. That has no source we know
    of, and individual differences are large (Itoh et al. 2007).
- **Proxies:**
  - (a) dT is at least +4.0 dB (the design gives about +6 dB);
  - (b) timbre, as in P5.

### H14. Image-source early reflections per role distance (profile V4)

- **Mechanism:**
  - Shoebox 10 x 8 x 3.2 m, with the listener at (3.0, 4.2, 1.2) m, facing +x. The off-centre
    position keeps image delays from coinciding.
  - Images up to second order; the 12 earliest are kept.
  - Each reflection carries:
    - its geometric delay relative to the direct sound;
    - a spreading gain `r_direct / r_image`;
    - per-bounce wall reflectance `sqrt(1 - alpha(f))`;
    - the ear filter (head, plus pinna and steering when enabled) at its arrival direction
      relative to the head.
  - Absorption alpha(f) is hand-chosen and rises with frequency. It is not taken from a measured
    table.
- **Role distances in Lite:**
  - Lite has no stems, so the pan position stands in for the role. Centre sectors (|theta| at most
    5 degrees) are near, at 1.0 m; 10 to 20 degrees are mid, at 2.0 m; 25 to 30 degrees are far,
    at 4.0 m.
  - The five buses are centre, mid left and right, and far left and right. Each is rendered at the
    mean rendered azimuth of its sectors.
  - The direct sound keeps unit gain, so the mix balance is unchanged. Distance enters only
    through the reflection and late levels.
  - The pan-to-role mapping is SPECULATIVE. It assumes the usual pop layout, with vocal, kick and
    bass in the centre.
- **Tag:** ESTABLISHED for the method (Allen and Berkley 1979) and for DRR as a distance cue
  (Zahorik 2002). SPECULATIVE for the Lite role mapping.
- **Proxies:**
  - (a) exactly 12 reflections, each delay within 0.5 samples of its geometry;
  - (b) DRR falls strictly from near to mid to far, by at least 2 dB per step, with near at
    least +6 dB. Early reflections only, so the steps are small.

### H15. FDN late field with controlled interaural coherence (profile V5)

- **Mechanism:**
  - 16 delay lines with a normalised Hadamard feedback matrix (orthogonal, so the loop is
    lossless).
  - Delays are primes near log-spaced targets from 23 to 53 ms.
  - Each line has a one-pole absorption filter whose DC and Nyquist gains give T60 of 0.60 s and
    0.25 s.
  - Two orthogonal output taps give two uncorrelated signals. They are mixed per STFT bin as
    `L = a Y1 + b Y2`, `R = a Y1 - b Y2`, with `a^2 - b^2 = gamma(f)`, outside the loop as in
    Menzer and Faller.
  - Target coherence: the free-field diffuse value `sin(kd)/(kd)` with d = 2a = 0.175 m. A real
    head lowers it faster, so this target is conservative toward too much correlation.
  - The late send per bus scales with distance (r / 2 m in amplitude), so the late-to-direct
    ratio grows with distance as in a real room.
  - The ambient part keeps its V0 decorrelated path and also feeds the late field.
- **Tag:**
  - ESTABLISHED: the FDN (Jot and Chaigne 1991), and coherence control outside the loop (Menzer
    and Faller 2009).
  - SPECULATIVE: the target curve. We use the free-field formula, not a measured binaural one,
    and checking it against a measured binaural curve is to do.
- **Proxies:**
  - (a) RT60 (T30 from Schroeder backward integration) in the 1 kHz octave within 0.51 to 0.69 s,
    and RT60 at 4 kHz below RT60 at 500 Hz;
  - (b) normalised echo density (20 ms window), averaged over 100 to 300 ms, at least 0.90;
  - (c) late-field coherence in the octaves from 125 Hz to 4 kHz within +/-0.15 of the target;
    coherence at 125 Hz at least 0.8, so the bass is not decorrelated (V0's ambient path
    decorrelates all frequencies);
  - (d) the DRR steps of H14, now with late energy, are at least 5 dB each (above Zahorik's
    5 to 6 dB thresholds at the lower end). Expected ranges: near +6 to +14 dB, mid 0 to +8 dB,
    far -6 to +3 dB.

### H16. Near-field low-frequency ILD for close roles (toggle `nearfield`, not in the V chain)

- **Mechanism:** A broadband per-ear gain from the straight-line distance to the near ear and the
  wrapped path to the far ear, for a source at the role distance. It is normalised so the summed
  power of the two ears is unchanged.
- **Tag:**
  - ESTABLISHED: the mechanism, that the ILD grows at low frequencies when a source is closer than
    about 1 m (Brungart and Rabinowitz 1999; Duda and Martens 1998; not re-read).
  - SPECULATIVE: our first-order geometry, which is not the spherical-head series solution.
- **Expected:** almost inert in Lite, because the near role is the centre, where the ILD is 0 by
  symmetry.
- **Proxies:**
  - (a) at 1.0 m and 60 degrees, the 200 Hz ILD is at least 1.0 dB;
  - (b) at 0 degrees, the ILD is below 0.01 dB in magnitude.

### H17. The soundfield is rotatable by re-indexing (the organising insight)

- **Mechanism:**
  - The ear filters are tabulated on a uniform 1 degree azimuth grid as magnitude and delay.
    Linear interpolation of magnitude and delay avoids the comb cancellation that interpolating
    complex responses causes (noted in 0006).
  - A head yaw `psi` renders every sector at `alpha_k - psi`. That is an index offset into the
    table plus one interpolation weight per sector: O(13) work per orientation update. The work
    per bin and frame is unchanged.
  - The late field is diffuse and does not need rotating.
  - Early reflections do: 12 directions per bus, recomputed in closed form.
- **Tag:**
  - ESTABLISHED: the computational claim, which is true by construction and tested.
  - ESTABLISHED: the perceptual value of *dynamic* head tracking (Brimijoin et al. 2013; Begault
    et al. 2001; Brown and Duda 1998: "head motion is highly effective in resolving front/back
    confusion").
  - SPECULATIVE, and not a head-motion cue at all: the offline renderer's fixed `look_yaw_deg`.
    It only tests the code path. A static rotation gives the ear no motion cue.
- **Proxies:**
  - (a) rotating by k grid steps equals rolling the table index, with zero error (better than
    1e-12);
  - (b) the error of interpolating halfway between grid points is at most 0.5 dB in magnitude and
    0.5 samples in delay.

### Rejected or deferred

- **Shoulder echo:** Brown and Duda dropped it after informal tests showed little effect on
  elevation. Deferred.
- **Objective externalisation metrics** (for example, statistics of ILD or IACC fluctuations): we
  found no metric we could verify in this spike, so none is claimed.
- **A measured HRTF:** out of scope for Lite (no datasets).

## Proxy table (gates decided in advance)

P1: front-rear tilt dT (dB, direct path). P2: DRR near / mid / far (dB). P3: late-field coherence
and IACC. P4: RT60 and echo density. P5: worst octave deviation from 125 Hz to 8 kHz (dB) on a
pink-noise test mix after RMS match. V0 measured 2.45 dB, at 4 kHz. P6: loudness: RMS change
before matching, and the residual after matching.

| Profile | P1 dT | P2 DRR | P3 coherence | P4 RT60 / NED | P5 timbre | P6 loudness |
|---|---|---|---|---|---|---|
| V0 current | 0.00 +/- 0.05 | direct only (no reflections) | ambient path: at most 0.1 in every octave, including 125 Hz | none | 2.45 (baseline) | raw within +/-1.5, residual at most 0.05 |
| V1 + front-arc | 0.00 +/- 0.05 | as V0 | as V0 | none | at most 3.45 | as V0 |
| V2 + pinna | at least +1.0 | as V0 | as V0 | none | at most 3.45 | raw within +/-3, residual at most 0.05 |
| V3 + bands | at least +4.0 | as V0 | as V0 | none | at most 3.45 | raw within +/-3, residual at most 0.05 |
| V4 + early reflections | V3 +/- 0.05 | near at least +6, strictly falling, steps at least 2 | as V0 | 12 reflections, delays within 0.5 samples | at most 4.0 | raw within +/-3, residual at most 0.05 |
| V5 + late FDN | V3 +/- 0.05 | near +6 to +14, mid 0 to +8, far -6 to +3, steps at least 5 | target +/-0.15 (125 Hz to 4 kHz), at 125 Hz at least 0.8 | 1 kHz in 0.51 to 0.69 s; 4 kHz below 500 Hz; NED (100 to 300 ms) at least 0.90 | at most 4.0 | raw within +/-3, residual at most 0.05 |

Extra gates: V1 lateral retention (H11b), V2 elevation notch (H12a), H16 (a, b), H17 (a, b).

The "max" profile combines the toggles whose gates pass. It is defined after the measurements
and is listed in the Results section.

## Decision

Run the spike as an ablation chain V0 to V5 in `stage.render.profiles`, behind
`render_stereo(profile=...)`, with the gates above as tests. Promote nothing to the default until
the blind test (`scripts/make_abx.py`, results in `experiments/results.csv`) has ranked the profiles.

## Consequences

- Every new cue can be switched off on its own.
- Proxies that fail are reported, not tuned away; a failing gate stays failing.
- Two patent reviews are open (see above).

## Results

To be filled in from the test output, without changing the gates above.
