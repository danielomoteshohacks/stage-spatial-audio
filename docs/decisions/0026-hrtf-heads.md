# 0026. Several measured heads, and a game that picks one

- Status: accepted
- Date: 2026-11-24

## Decision

- `tools/hrtf-pack/build_pack.py --subject` builds one pack per SADIE II subject (D1 KU100, D2
  KEMAR, human subjects H3 to H8 by default) in the `hrtf-heads` workflow; the release
  `hrtf-heads-v1` carries the packs and an index with each file's size and SHA-256. SADIE II is
  Apache-2.0 (the Zenodo record's licence field is checked by the builder, which refuses
  anything else). The Space downloads a head on first use and verifies it; a head that is not
  present falls back to D1, then to the analytic head, and the plan records the head used.
- `stage.spatial.heads.select_head` chooses the head from the listener's calibration answers:
  the head with the smallest mean angular error plus 60 degrees times its front-back-confusion
  rate (a confusion is a 180 degree mistake; the weight is a design choice, SPECULATIVE); ties go
  to D1.
- The web app's two-minute game (decision 0029) plays short sounds from directions through each
  candidate head in turn, the listener taps where each came from, and the result is stored on the
  device and sent with every render (`hrtf` in the render request and the plan). The results
  export (CSV) carries each trial's true and answered direction, so front-back confusion and
  angular error before and after can be measured on willing listeners; the numbers will be
  published only when there are listeners.

## Not done

The subject list was chosen without being able to read the Zenodo record's file list from the
cloud session (the host is not on its allow-list); the workflow fails a subject loudly if the
record lacks it, and the index lists what was built. Which human subjects best fit most listeners is
not known; D1 stays the default.
