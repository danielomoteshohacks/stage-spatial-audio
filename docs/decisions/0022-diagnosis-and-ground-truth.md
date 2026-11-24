# 0022. Why v2 sounded like "stereo pushed backwards", and the ground-truth benchmark

- Status: accepted
- Date: 2026-11-24

## Context

The owner's verdict on v2 was that the upmix "just takes the stereo sound and pushes it a bit
backwards in space". Before changing the renderer, v3 measures what v2 actually does, and builds
a benchmark where the right answer is known.

## Decision

1. **Measure where the energy goes** (`stage.metrics.spatial`, `scripts/spatial_diagnose.py`).
   Each plan object is a set of feeds (directions with energy shares). The object's measured
   energy above the bass crossover is shared over its feeds and split into direct, early (under
   80 ms) and late parts by the energy of the impulse response the renderer used. Reported:
   direct energy in the front (|az| <= 30), sides, rear and height (el >= 25); the share outside
   the front by azimuth; the number of independent directions (merged within 20 degrees) with at
   least 5 percent of the direct energy; the direct-to-reverberant ratio per object; the late
   share; IACC (500 Hz to 4 kHz, +/- 1 ms). Status of the method: ESTABLISHED for IACC (ISO
   3382-1) and for the direct/early/late split (the usual 80 ms limit, ISO 3382-1 clarity);
   SPECULATIVE for the direction map as a stand-in for perceived spaciousness: it is a model of
   the renderer's output, not a listening result.
2. **Ground truth** (`stage.groundtruth`, `scripts/benchmark_groundtruth.py`). Fifteen synthetic
   leaves (lead vocal, two backing vocals, kick, snare, hats, two toms, bass, two double-tracked
   guitars, keys, two pads, a riser) each have a position. The truth is every leaf dry through the
   measured HRTF at that position; the release is the stereo fold by sine of azimuth (rear folds
   to the front, height is lost). SoundStage sees only the release. Scores: SDR per leaf (plain
   SDR, labelled so), the earth mover's distance between the render's direction map and the
   truth's (degrees of great-circle travel), and per-leaf angular error (RMS, energy weighted,
   over the feeds of the objects that carry the leaf's stem; spread copies around the true place
   count as error).

## Findings on v2 (3 benchmark songs, 30 s each, five variants; docs/log.md has the table)

| Suspect | Verdict | Number |
|---|---|---|
| Objects confined to az +/- spread/2 around the front | Confirmed | 83.0% of direct energy in the front +/- 30, 17.0% outside, 3.0 independent directions, 0.0% rear, 0.0% height |
| Room sends on every object | Confirmed | Median object DRR -6.1 dB: the room carries 62% of the energy; with the send set to zero the IACC rises from 0.83 to 0.94, so the room is where the externalisation came from |
| Living-room default | Confirmed | The studio gives a median DRR of +17 dB and IACC 0.97 (in the head): v2 chose the living room because it was the only space that sounded outside the head |
| Ambience carrying the surround | Confirmed | Rear and height direct energy 0.0%: the bed holds the residual of the mix, which is a fraction of a percent of its energy |
| BED_FRONT_SHARE | Rejected | Setting it to 0 changes nothing to three decimals: the bed has no energy to redistribute |
| Only four stems | Confirmed | On the ground-truth songs v2's map is 24 degrees (earth mover's) from the truth and its per-leaf angular error is 72 degrees RMS: it cannot put the left guitar left and the right guitar right, because both are one `other` stem |
| Late tails (over 80 ms) | Rejected as the main cause | Late share of the energy is 6.4%; the room is mostly early reflections (third-order images in a 0.5 s room) and the template `room_send` scales only the late field |

The ground truth of the same songs has 31% of its direct energy outside the front (azimuth), 10%
in the height layer and 65% in the front; v2 has 13 to 15% and 0.2%.

## Consequences

- v3 must get its externalisation from direction and distance cues and a sparse early set, with
  a dry default space (decision 0025), and from many more objects than four stems (decision 0023).
- The brief's gate "direct energy outside the front +/- 30 degrees at least 3x v2's share" can be
  tested exactly, but note the cap: protected objects (lead vocal, kick, snare, bass) never move
  and carry most of the energy in the generated songs, so outside-front share cannot exceed the
  energy share of the unprotected leaves. Decision 0027 reports the measured ratio next to that
  cap and sets the target at the ground truth's share, within 10 points.
- A per-leaf angular error target is set in decision 0027 from the localisation accuracy of
  non-individual HRTFs.
