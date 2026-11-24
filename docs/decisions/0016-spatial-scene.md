# 0016. From a stereo mix to a spatial scene: decomposition, objects and an enveloping bed

- Status: accepted
- Date: 2026-11-24

## Context

The owner wants a moving, enveloping scene that stays true to the record: the bass stays the
bass and the vocal stays where the artist put it. Phase 1 alone renders the stereo pair through
two virtual loudspeakers in a room; that externalises the mix but does not surround the
listener.

## Decision (`stage.scene.render`)

1. **Low end.** Below the plan's crossover (120 Hz) the original passes untouched (zero-phase
   Linkwitz-Riley, decision 0014). Reflections, the late field and every decorrelated bed feed
   are additionally high-passed at 200 Hz, because around the crossover the untouched bass and
   the rendered band overlap, and reverberant or decorrelated energy there adds incoherently: the
   first Lite scene render read 6.4 dB off at 125 Hz; with the high-pass it reads 1.7 dB.
2. **Decomposition per stem.** Harmonic/percussive separation by median filtering (Fitzgerald
   2010) with the percussive part as the exact remainder; the harmonic part split into primary
   and ambient (stage.analysis.stereo, Avendano and Jot 2004). Transients go to the direct path
   and are only ever convolved with fixed or slowly cross-faded head and room responses, never
   gated per bin, so they are not smeared. Drums are also split at 4 kHz into kit and
   hats/percussion.
3. **Objects to virtual sources.** Each plan object is a pair of virtual sources at
   az +/- spread/2 carrying the part's own left and right channels, so the record's image stays
   inside the pair (the artist's placement is kept); a zero spread gives one centred source.
   Objects with a `wide` setting cross-fade (equal power) between a narrow and a wide pair as the
   sections open.
4. **Bed.** Ambient objects without a spread keep 40 percent of their energy on the front pair
   and open the rest into the 7.1.4 side, rear and top positions (ITU-R BS.2051 System J) through
   velvet-noise decorrelators (Alary, Politis and Valimaki 2017), 25 ms, a different seed per
   loudspeaker, with transient gating: around onsets the output cross-fades back to the dry
   signal. Bed gains follow the template and the section openness (heights rise most).
5. **Distance** (item 15). Level falls with the square root of distance from 1.5 m, limited to
   -4.4 to +4.1 dB (a gentle law: the inverse law would rewrite the mix balance); the
   direct-to-reverberant ratio follows the room model (0013); ISO 9613-1 air absorption along the
   direct path; below 1 m an extra interaural level difference, largest below 1 kHz, as the
   near-field cue of a spherical head (Duda and Martens 1998; Brungart and Rabinowitz 1999,
   magnitude SPECULATIVE).
6. **7.1.4 export.** The same virtual sources are panned to the 12 loudspeakers (pairwise in the
   middle and upper rings, then between rings by elevation, power-normalised), the low band goes
   to L and R unchanged, and the result is written as a 24-bit 12-channel WAV on request.
7. **Neutrality.** One timbre-correction filter and one loudness gain for the whole upper band
   and every object stem (decision 0014), so the object stems plus the low end sum to the render
   exactly (to 1e-16 in the tests).

8. **Room distance** (added in Phase 6): the room model places each object at its template
   distance times the space's listening distance over 2 m (the template's home scale), so a hall
   is heard from a seat in it; level and near-field cues keep the template distance. Without this
   the club and the hall were barely more spacious than v1 (decision 0021).

## Covariance-domain rendering and patents

Vilkamo, Backstrom and Kuntz (JAES 2013, "Optimized covariance domain framework for
time-frequency processing of spatial audio") hit a target interaural covariance with the least
decorrelated energy, and Vilkamo and Pulkki analyse how decorrelators cause artifacts. That
optimal mixing is not implemented: Fraunhofer patents EP2560161 and US10339908 relate to it, and
the owner has not decided on licensing. The default path is the non-patent velvet-noise bed with
transient gating described above. Both papers are cited from the abstracts and the patent
numbers given in the task; neither paper could be opened from this session.

## Measured (generated test songs, 30 s excerpt, guard report)

| Render | Verdict | Timbre max | Bass correlation | Alignment | Artifact flags | Time |
|---|---|---|---|---|---|---|
| Scene, stems, Afrobeats, living room | pass | 1.8 dB | 0.9995 | 0.02 ms | 0 | 27 s |
| Scene, stems, House, club | pass | 2.6 dB | 0.9999 | 0.16 ms | 0 | 29 s |
| Scene, stems, Hip-hop, studio | pass | 1.3 dB | 0.9999 | 0.00 ms | 0 | 23 s |
| Scene, Lite, Afrobeats, living room | review | 1.7 dB | 0.9996 | 1.5 to 1.9 ms | 0 | 15 s |

The Lite alignment reading is the guard's estimator struggling with sustained synthetic chords
on a reverberant render, not a measured delay (the same renderer reads 0.02 ms on the other test
signal); it stays "review" until the estimator is improved.

## Sources

ESTABLISHED (methods as published, implemented here): Fitzgerald 2010; Avendano and Jot 2004
(already in decision 0004); Alary, Politis and Valimaki 2017 and Karjalainen and Jarvelainen 2007
for velvet noise; ITU-R BS.2051 for the layout. Cited without being re-read in this session:
Vilkamo et al. 2013, Vilkamo and Pulkki, Duda and Martens 1998, Brungart and Rabinowitz 1999.
SPECULATIVE: the bed shares, the square-root distance law, the near-field magnitude.
