# 0018. Motion that is felt: tempo-locked paths, a speed cap and protected anchors

- Status: accepted
- Date: 2026-11-24

## Decision

- Selected objects (shakers, hats, percussion, in some templates) move on smooth paths: an
  orbit (a constant-speed turn) or a sway (a sinusoid), with a period of a whole number of bars
  and phase zero on the first downbeat, so motion is locked to the groove. The scene also
  breathes: section openness (verse about 0.35, chorus 0.9, drop 1.0, with a one-bar raised-cosine
  between sections) widens and lifts the wide objects and raises the bed, heights most.
- The lead vocal, the bass and the kit never move (protected; `validate_plan` refuses a plan
  that moves one).
- Motion depth (0 to 1) is the listener's control and scales every path; 0 is a static scene.
- Speed cap: 45 degrees per second. A path that would be faster has its period doubled until it
  is not (tested). Rotating sound fields can induce illusory self-motion and discomfort in some
  listeners (Valjamae 2009, Brain Research Reviews 61(2), a review of auditory vection, cited
  from its abstract; not re-read here); the cap is a conservative choice, SPECULATIVE as a
  threshold, and a full orbit therefore takes at least 8 s.
- Rendering: the direct sound of a moving source is rendered in 50 percent overlapped Hann blocks
  of 1024 samples, each through the head filter at that block's direction. Because the filters
  change by at most 0.5 dB per degree in azimuth (decision 0012) and a block moves at most
  0.5 degrees at the cap, the cross-fade between blocks cannot click. Reflections and the late
  field are those of the mean position.
