# 0032. The record's centre and body stay in front

- Status: accepted
- Date: 2026-11-25

## Context

After decision 0031 the owner still found the stereo original better than the spatial version.
Tracing a whole streamed job showed two problems the width fix did not touch:

1. **The body of the song was sent behind the listener.** The cascade labelled the "other" stem
   (everything a four- or six-stem model does not name: in most songs the chords, keys, guitars
   and synths) with the `pad` role, which places it at 130 degrees and 30 up, breathing and
   lifting. The harmonic body of the record came from behind and above, through head filters
   that dull it.
2. **The centre went through a head filter.** Lead vocal, kick, snare and every part's centre
   were rendered from straight ahead through the measured head, which colours them (the dip and
   peaks of a dummy head's frontal response) and, with a non-individual head, often places them
   inside or above the head.

## Decision

1. "other" keeps the `other` role: its centre in front, its sides at +/-70 degrees, 5 up; a
   one-sided cluster at 65 degrees.
2. The record's centre is left as the record has it: any part's centre feed straight ahead (at
   most 15 degrees up) reaches both ears through a flat, equal impulse at the head filter's
   arrival time and energy, not through the head filter. Only what was beside the listener in the
   mix is moved around them (plan key `centre`: `record`, the default; `hrtf` restores the old
   behaviour).

## Measured

Correlation of the render's mid with the record's mid, 2 to 8 kHz, on a generated song: the
`other` stem's sides at +/-70 degrees account for nearly all of the difference from the record
(0.54 with them, 0.91 with that one part centred). This is partly the measure itself (two ears
summed, so lateral sources comb), so it is reported, not used as a gate. The listening decides.
