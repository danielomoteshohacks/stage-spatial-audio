# src/stage

The Python package. It is the **reference implementation** (the oracle): other implementations
must match its golden files.

| Subpackage | Purpose | Status |
|---|---|---|
| `io` | Audio read and write, resampling, loudness, identifiers | planned (slice 1) |
| `analysis` | STFT, panning factor, coherence, primary and ambient split, style features | planned (slice 1) |
| `render` | Sectors, widen warp, HRTF filtering, reflections, tail, timbre bound | planned (slices 1 and 2) |
| `guard` | Fidelity checks and the quality report | planned (slice 2) |
| `mixplan` | Roles, distances, templates, masking-aware placement, plan writer | planned (slice 3) |
| `separation` | Fast model, triage-and-refine, residual and consistency | planned (slice 3) |
