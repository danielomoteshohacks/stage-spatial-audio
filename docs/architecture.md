# Architecture

Stage turns one stereo master into a spatial render by keeping every sound where the stereo mix
already places it, widening those positions, giving each role its own distance, and adding a room.

```mermaid
flowchart LR
    A[Stereo master or stem] --> B[STFT]
    B --> C[Pan and coherence analysis]
    C --> D[Primary p and ambient a<br/>p + a = input]
    D --> E[13 pan sectors]
    E --> F[Widen warp<br/>order preserving]
    F --> G[HRTF per sector]
    D --> H[Ambient to decorrelated tail]
    G --> I[Near, mid, far reflection buses]
    H --> I
    I --> J[Timbre bound]
    J --> K[Fidelity guard]
    K --> L[Binaural stereo output]
```

## Tiers

| Tier | Needs a neural network | Runs where | Input to the flow |
|---|---|---|---|
| Lite | No | On the device, real time | The whole mix |
| Standard | Yes, small | Offline, once per track | Each stem |
| Studio | Yes, small plus refiner | Offline, once per track | Cleaner stems |

## Contracts between stages

Stages exchange only files with schemas in [`schemas/`](../schemas/): the **plan**, the
**report** and the **consent** record. Audio is 44.1 kHz stereo, computed in 32-bit float and
stored as 24-bit FLAC. A render has exactly the same length as its input.

## Mapping from the specification to this repository

| Specification | Here |
|---|---|
| Python reference renderer and analysis | `src/stage/analysis`, `src/stage/render` |
| Offline engine (separation, plan, guard) | `src/stage/separation`, `mixplan`, `guard` |
| Rust real-time core | `stage-core/` |
| HRTF pack tool | `tools/hrtf-pack/` |
| Web demo | `web/` |
