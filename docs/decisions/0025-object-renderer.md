# 0025. The object renderer: dry point sources, a sparse early set, the record's own reverb returned

- Status: accepted
- Date: 2026-11-24

## Decision

`stage.scene3.render.render_v3` renders every object of a v3 plan straight to binaural through the
measured HRTF at its azimuth and elevation (full sphere, interpolated without combing, decision
0012). No virtual loudspeakers, no panning law, no per-object reverb send.

1. **The space is the Dry stage** (`configs/spaces/spaces.json`): 7 x 5.2 x 3 m, RT60 0.05 to 0.14 s,
   reflection level 19 dB under the diffuse-room prediction (6 dB under the studio's measured fit),
   image sources to order 2, so every reflection arrives within about 60 ms of the direct sound.
   Only the direct sound and the early reflections are built (`brir(..., late=False)`): there
   is no late field. Reflection level grows with distance (half to double). Ceiling and floor
   reflections come from the same image-source model, so they follow the elevation of the
   source. Long-tail spaces remain selectable by the listener.
2. **Distance** is level (the v2 square-root law from 1.5 m), air absorption (ISO 9613-1), the
   near-field interaural level difference below 1 m (Brungart and Rabinowitz 1999) and the
   reflection level.
3. **Mono and pairs.** Mono objects use the mid signal with the stereo leaf's energy restored (a
   hard-panned source is not 3 dB down); pairs feed the left and right channels to two sources at
   +/- azimuth, so the record's own panning inside the pair is kept.
4. **The record's reverb.** Where level 5 split a part into dry and reverb, the reverb is
   decorrelated (velvet noise with transient gating) and fed to the sides (30 percent), rear
   (30 percent) and height (40 percent) positions, none in front, at its original level
   (distance 1.5 m, gain 0 dB times the genre and character factors). It is the only reverberation
   added by default, and the diagnostics count it as late energy.
5. **Paths.** Objects with events or breathing are rendered per 1024-sample Hann block at 50
   percent overlap, one head filter per distinct (1 degree, 2 degree) position.
6. **Directional bands** (off by default; `directional_db` up to 2 dB): Blauert's bands as
   smooth Gaussian bumps, equal in both ears. SPECULATIVE; bounded by a test and by the guard.
7. **Preserve the record.** The bass bypass, timbre matching and loudness matching of v2 are
   reused unchanged; the object stems and the untouched low band sum to the render (tested to
   2e-3); the guard runs on every render.
8. **The 7.1.4 bed** is now only an export (objects at their mean positions, the returned
   reverb at its ring), no longer part of how the headphone render is made.

## Measured (generated ground-truth songs, true leaves, 30 s, two songs; v2 with the true four
stems in the living room, its default)

| | v2 | v3 | Truth |
|---|---|---|---|
| Direct energy outside the front +/-30 (azimuth) | 13.2% and 15.0% | 42.3% and 43.3% | 31% |
| Height layer (elevation 25 and above) | 0.2% | 8.8% and 9.0% | 9.7% |
| Median object direct-to-reverberant ratio | -6.1 dB | +26 dB | n/a |
| Late (over 80 ms) energy share | 6.6% | 0.0% | 0% |
| IACC | 0.72 | 0.53 | n/a |
| Direction-map distance to the truth | 24.7 and 24.3 degrees | 12.5 and 12.6 degrees | 0 |
| Per-leaf angular error, RMS | 51 degrees | 16.4 degrees | 0 |
| Timbre deviation | 1.7 dB | 0.8 dB | n/a |
| Guard | pass | pass | |

The outside-front ratio is 3.2 on the first song and 2.9 on the second (3.0 on average): at the
brief's threshold, not above it, and above the truth's own share, which is why the placement is not
pushed wider. The render time of the first render in a process is dominated by building each
position's early-reflection response; in steady state a 10 s excerpt takes 1.1 s (Phase 3 speeds
up and publishes the table).

## Consequences

- The Space needs no new dependency for the renderer. The v2 engine stays (the Lite and v2
  profiles and their tests are untouched).
- The listener's choices that remain: space (the dry stage by default), character, motion depth,
  genre, head (decision 0026).
