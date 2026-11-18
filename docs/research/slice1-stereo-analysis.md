# Slice 1: stereo analysis notes

Implementation: `src/stage/analysis/`. Tests: `tests/unit/test_stereo_analysis.py`,
`tests/property/test_primary_ambient.py`.

## Model
Each time-frequency bin of the stereo pair is `X = p * u + a`, with `u = [cos(phi), sin(phi)]`
the panning direction of one dominant primary sound and `a` the ambient remainder.
The primary is the projection of X onto u, so `primary + ambient = X` exactly, and the ambient
part is orthogonal to u. Energy therefore splits exactly: `|X|^2 = |primary|^2 + |ambient|^2`.

## One refinement to the specification
The specification defines coherence as `|P_LR| / sqrt(P_LL P_RR)`. The code also returns
`inphase_coherence = max(Re P_LR, 0) / sqrt(P_LL P_RR)`. A time-delayed pair (spaced
microphones) has high `|P_LR|` but is not amplitude-panned, and the real part is the statistic
that matches the amplitude-panning model. Gating on `inphase_coherence` makes the method degrade
gracefully on that kind of recording. `tests/unit/test_stereo_analysis.py` checks both cases.

## Design choices
* Causal one-pole smoothing over time (80 ms) plus a 5-bin box over frequency, so the Rust
  real-time core can reproduce the numbers exactly.
* A unit direction vector instead of the panning factor k, which avoids infinities at hard pan.
* Silent bins are treated as centred, never as hard left.

## Open questions (to settle by listening)
* Is 80 ms the right time constant for music with fast transients?
* How many neighbouring bins should be averaged?
