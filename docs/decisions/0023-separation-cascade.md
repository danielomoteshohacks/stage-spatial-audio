# 0023. A hierarchical separation cascade with our own post-processing

- Status: accepted
- Date: 2026-11-24

## Context

v2 separated four stems. Four stems cannot place a left guitar and a right guitar apart, split a
kit into its pieces, or tell a lead vocal from its harmonies (decision 0022 measured the cost).
Research (docs/research/separation-v3.md) says the winning systems are cascades of specialised
models, ensembles weighted on a validation set, and dereverberation used on vocals with a guard.

## Decision

`stage.separation.cascade` implements six levels, each an engine behind a manifest entry
(configs/cascade/models.json: source, licence as read, the author's SDR with its set, size,
SHA-256), cached per track by content hash:

1. vocals vs instrumental: an ensemble combined per frequency band with weights fitted on a
   validation set by non-negative least squares (`ensemble.py`);
2. lead vs backing vocals (a karaoke model, else the pan rules);
3. instrumental into bass, drums, guitar, piano, other (a 6-stem model, else the four-stem
   fallback chain);
4. drums into kick, snare, toms, hi-hat, cymbals (a drum model, else band and pan rules);
5. dry and reverb: the vocal dereverberator on the lead vocal, the model-free late-reverberation
   subtractor on every other melodic stem, both behind a 10 dB guard; the reverb is kept as its
   own part and re-spatialised later (decision 0025);
6. azimuth split (ADRess, soft masks) of backing, guitar, piano and other.

The post-processing layer (`post.py`): multichannel Wiener refinement, a mixture-consistency
projection, bleed suppression, musical-noise detection with targeted repair, transient
restoration, and a per-leaf quality score that lets the scene planner merge a poor leaf back into
its parent. Each step is kept or switched off by a measurement (ablation table in
docs/research/separation-v3.md): Wiener and consistency and targeted repair are on; bleed
suppression and transient restoration are implemented, tested and off by default because they did
not help on the generated songs.

Licences are enforced in code (`config.usable`): `open` and `copyleft` and `nc` models run, a model
whose licence is not stated (`unverified`, the 6-stem BS-RoFormer SW) does not unless the owner
enables it; the report records every model used and every one skipped, with the reason.

Presets: `best` (every level), `fast` (one vocal model, one 6-stem model, DSP for the rest), `cpu`
(four-stem fallback and the model-free levels). `scripts/measure_cascade.py` reports GPU seconds
per audio minute per model on the Space.

## Consequences

- Nothing neural could be run in the cloud session that wrote this (no GPU; the checkpoint hosts
  are not on its network allow-list), so the GPU figures and the first real-weights run are
  owed to the Space (the log says so). The plumbing is tested with a tiny randomly initialised
  network through the same loader.
- The SoundStage Separator is now distilled from the cascade (training/README.md); its release
  gate (stage-4 average SDR at least htdemucs') is unchanged.
- Whole-song processing runs the Wiener step in 30 s chunks with cross-fades, so memory is
  bounded.
