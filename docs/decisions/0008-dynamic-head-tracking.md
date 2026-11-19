# 0008. Dynamic head tracking in the real-time path: rotate the soundfield by re-indexing

- Status: proposed (design only; nothing here is implemented except the Python reference of
  the rotation, `stage.render.rotation`, tested under H17 in 0007)
- Date: 2026-11-19

## Context

Head movement is one of the strongest cues there are for externalisation and for telling front
from back:

- Virtual sounds fixed to the world were externalised 65 percent of the time, against 20 percent
  for sounds fixed to the head (Brimijoin, Boyd and Akeroyd, PLOS ONE 2013).
- Brown and Duda (1998) note that "head motion is highly effective in resolving front/back
  confusion".

The offline renderer cannot use this, because a file has no listener. Its `look_yaw_deg` only
tests the code path.

## Why the sector representation makes this cheap

Lite already splits the primary into 13 sectors, each rendered at a fixed direction `alpha_k`
around the listener. A head yaw `psi` changes only *where each sector is heard from*: sector `k`
is now at `alpha_k - psi`.

- **Direct path.** The ear filters are tabulated on a uniform azimuth grid, as a delay per ear
  plus a residual response (`AzimuthFilterBank`). A rotation is an index offset and one
  interpolation weight per sector: 13 lookups per orientation update.
  - Measured in the Python reference: rotating by k steps equals rolling the table, with error
    at most 1e-12. Halfway between 1 degree grid points the error is at most 0.017 dB.
  - The work per bin and frame (13 complex multiply-adds per ear) does not change. No filter is
    redesigned, so tracking costs nothing extra per sample.
- **Late field.** It is diffuse (coherence set per frequency, not per direction), so it needs no
  rotation.
- **Early reflections** do need rotating: 5 buses times 12 reflections, each a closed-form ear
  filter at a new direction. Recompute them at the control rate, not the audio rate, and
  crossfade the old and new FIRs over one block.
- **Pitch and roll** give the sectors an elevation. That needs either a two-dimensional table
  (azimuth by elevation) or the closed-form `ear_filters` at 13 directions per update. Both are
  control-rate work. Start with yaw only, which is the dominant natural head movement, and add
  pitch and roll after measuring.

This is the claim the spike set out to test, and it holds for the direct path: tracking is a
re-indexing. It does not hold for free for the early reflections, which cost one closed-form
recomputation per update.

## Interface the Rust core must expose

```rust
pub struct Orientation { pub yaw_deg: f32, pub pitch_deg: f32, pub roll_deg: f32, pub t_us: u64 }

impl StageRenderer {
    /// Fixed at creation: sample rate, block size, profile (cue toggles), beta.
    pub fn new(cfg: &RenderConfig) -> Self;
    /// Control thread. Lock-free (a single-slot atomic or ring buffer); never blocks the audio thread.
    pub fn set_orientation(&self, o: Orientation);
    /// Audio thread. Stereo in, binaural out, same length; uses the newest orientation at block start.
    pub fn process(&mut self, input: &[f32], output: &mut [f32]);
    /// Measured algorithmic latency in samples, for the latency budget below.
    pub fn latency_samples(&self) -> u32;
}
```

Conventions are those of the Python reference:

- Yaw is positive when the head turns right, so the sources move left.
- Azimuth 0 is ahead and positive is to the right.
- Golden files: for any yaw `psi`, the Rust output must match
  `render_stereo(x, profile=Profile(..., look_yaw_deg=psi))` to the agreed tolerance. The Python
  `AzimuthFilterBank` is the reference for the table and the interpolation.

Browser and WASM wiring:

- The renderer runs in an `AudioWorklet`.
- Orientation goes from the main thread to the worklet through a `SharedArrayBuffer`. That needs
  cross-origin isolation; the fallback is `postMessage`.
- Sources of orientation, in order of honesty about what they measure:
  1. **WebXR viewer pose** (a headset): a true head pose.
  2. **Earbuds with a motion sensor** through a native app API: a true head pose. This is
     *not available to a web page*, so it belongs to the native app path.
  3. **The phone's `deviceorientation` event**: this measures **the phone, not the head**. It is
     only right when the phone moves with the head, for example held in front of the face while
     the listener turns. Otherwise it gives a "turn the phone to look around the stage"
     interaction. That is a different feature, and it must not be advertised as head tracking.
  4. **Front-camera face pose**: a true head pose without special hardware. A Lite build would
     need a classical, non-neural tracker. SPECULATIVE; deferred.

## Latency budget

From Lindau (DAGA 2009, n = 22, dynamic binaural synthesis):

- The mean detection threshold for total system latency was 107.6 ms (SD 30.4, 95 percent CI
  101.3 to 114 ms).
- The lowest single threshold was 52 ms, and only 3.4 percent of thresholds were 64 ms or below.
- Earlier studies' lowest thresholds were 60 ms (Brungart et al. 2005) and 75 ms (Yairi et
  al. 2006).

**Target: motion-to-sound of at most 40 ms**, below the lowest threshold measured. The
components:

| Component | Budget | Status |
|---|---|---|
| Sensor sample and event delivery | <= 10 ms | Not measured. `deviceorientation` rates differ by browser and device; measure them |
| Main thread to worklet | <= 3 ms (one 128-sample render quantum at 44.1 kHz is 2.9 ms) | Design |
| Algorithmic latency of the renderer | <= 12 ms | **The current reference fails this.** n_fft 2048, hop 1024 is about 46 ms on its own. The real-time path needs about n_fft 512, hop 256 (11.6 ms), or orientation applied per hop with a crossfade. Smaller frames change the stereo analysis and need their own tests |
| Audio output (`AudioContext.outputLatency`) | <= 15 ms | Device dependent. Wired output may fit. **Bluetooth adds its own buffering**, which must be measured per device and very probably breaks the budget |

If the measured total exceeds 40 ms, the options are: extrapolate the orientation forward by the
measured latency using the angular velocity (common in VR, SPECULATIVE for audio here), turn
tracking off for that output, or warn the listener. The release gate is an end-to-end measurement:
a recorded step in head angle against the rendered step, on real devices.

## Why this is the differentiator, said honestly

Head tracking itself is not new. Commercial products already rotate a binaural render with the
head, but they need particular earbuds and, mostly, content mixed in a particular immersive
format. Stage's difference is the combination:

- **Any song.** The scene comes from the ordinary stereo mix (pan-anchored rendering, 0004), so
  every track in a catalogue can be rotated, not only immersive mixes.
- **Any headphones for the render, any orientation source for the tracking.** The core takes
  orientation as plain input, whichever of the four sources supplies it.
- **Cheap.** Rotation is a table re-index, so it fits the Lite tier on a phone (to be confirmed by
  H8's CPU budget).

What we do **not** claim:

- That it sounds better than the hardware solutions. No such test has been run.
- That a phone gyroscope tracks the head. It does not, except when the phone moves with the head.
- That our rear cues are good. The pinna is extrapolated behind the head (0007, H12, SPECULATIVE),
  and a rotation that brings a source behind the listener depends on those cues and on the
  steering EQ. A listening test with tracking is needed before any claim.

## Patent flag

Head-tracked rotation of a set of virtual sources (virtual loudspeakers, Ambisonic rotation) is a
crowded field, and many filings cover specific combinations. The basic idea of rotating a set of
virtual sources predates most of them. This design must still get a claims review before shipping
(CLAUDE.md: flag any doubt), together with the two flags in 0007.

## Decision

Build the real-time core so that orientation is an input from the start, with yaw rotation by
re-indexing. Measure motion-to-sound latency on real devices before advertising head tracking.
Advertise it only for orientation sources that measure the head.

## Consequences

- The real-time STFT must be shorter than the offline reference's, a separate piece of work with
  its own golden files.
- The early reflections need a control-rate update and a crossfade.
- The phone-only web demo cannot honestly be called head-tracked. A WebXR or native earbud path
  can.

## Alternatives considered

- **Re-render from a full HRTF per source on every update:** costs more per update and needs
  HRTF data, which Lite does not have.
- **Ambisonic encode, rotate, binaural decode:** rotation is also cheap, but it needs an
  Ambisonic decoder with HRTFs and adds a format that the pan-anchored sectors do not need.
