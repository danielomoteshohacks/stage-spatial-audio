# 0031. Never narrower than the record: centre/side upmix per part and a width matcher

- Status: accepted
- Date: 2026-11-25

## Context

The owner listened to v3 on real catalogue songs and reported that the spatial version sounds
like mono: narrower and less clear than the original, with the instruments squashed together.
Measured on the generated songs (300 Hz to 8 kHz, four oracle stems, the `cpu` preset):

| | side-to-mid energy | inter-channel correlation |
|---|---|---|
| The record | 0.27 | 0.58 |
| v3 render | 0.06 | 0.89 |

So the complaint was right, and large: the render had a fifth of the record's width.

Two causes in the object renderer:

1. **Mono objects.** Lead vocal, kick, snare and bass were one point source fed by the mid
   signal. With four-stem separation the "vocals" stem holds the doubles, harmonies and the
   vocal reverb, and all of it collapsed to one point in front.
2. **Pairs fed by raw L and R.** "Other" and "drums" (which fell to the `other` role) were two
   sources at +/-85 degrees fed by the left and right channels. Everything the part has in the
   centre (the kick and snare inside "drums") reached both sources and became a phantom image
   between two directions 170 degrees apart through head filters: hollow and vague.

A third, physical cause: head filters send every source to both ears, so binaural audio is
always more correlated between the ears than headphone stereo, where a hard-panned part is in
one ear only.

## Decision

1. **Centre/side upmix per part** (`stage.spatial.upmix.centre_sides`), after Avendano and Jot
   (JAES 52, 2004): per time-frequency tile, psi = 2|S_LR| / (S_LL + S_RR) with statistics
   smoothed over 40 ms, centre = psi^3 (L + R) / 2, sides = each channel minus the centre in the
   time domain. Left = centre + left side and right = centre + right side exactly. ESTABLISHED
   (the similarity measure and the centre extraction are the paper's; the exponent and the
   smoothing are ours, SPECULATIVE in their values).
2. **Placement.** A `pair` role becomes `upmix`: its centre at the front of the object, each side
   out at +/-az. A `mono` role with `side_w` (lead vocal 35, kick 20, snare 25, bass 20) keeps
   its own width around its position. A new `drums` role holds a whole four-stem kit: centre in
   front, sides at +/-70 degrees and 10 up, protected.
3. **Width matcher** (`width_filter`, `apply_width`): per 1/3-octave band, lift the render's side
   channel by the dB that brings its side-to-mid ratio up to the record's, never down, at most
   9 dB, smoothed across bands. It runs before the timbre matcher.

## Result

| | side-to-mid | correlation |
|---|---|---|
| The record | 0.27 | 0.58 |
| v3 | 0.06 | 0.89 |
| Upmix only | 0.12 | 0.78 |
| Upmix and width matcher | 0.26 | 0.59 |

`tests/unit/test_upmix.py` keeps the render between 0.85 and 2 times the record's width.

## What this is not

This does not use Dolby's or Sony's code: both renderers are proprietary and closed. It uses
the published principles they are built on (object panning, binaural rendering through measured
head filters, centre/ambience upmixing). Whether it now sounds wide and clear is for listening to
decide; these numbers only show it is no longer measurably narrower than the record.
