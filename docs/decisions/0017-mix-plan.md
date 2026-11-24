# 0017. The spatial mix plan: analysis, genre templates and plan.json as the contract

- Status: accepted
- Date: 2026-11-24

## Decision

- **Analysis** (`stage.scene.analysis`): SuperFlux-style onset strength (Bock and Widmer 2013),
  autocorrelation tempo with a log-normal prior at 120 BPM and Ellis' dynamic-programming beat
  tracker (Ellis 2007), downbeats from the beat phase with the most low-band onset strength,
  Foote novelty sections (Foote 2000) on beat-synchronous band energies, snapped to downbeats,
  and energy-rank labels (intro, verse, pre-chorus, chorus, drop, bridge, outro). Labels are a
  heuristic and are recorded as such. Measured on three generated songs (98, 112, 124 BPM):
  tempo within 0.1 BPM, every chorus start within a bar.
- **Genre** (`stage.scene.genre`): the AudioSet Audio Spectrogram Transformer
  (MIT/ast-finetuned-audioset-10-10-0.4593, Gong, Chung and Glass 2021) through transformers,
  loaded only after the hub model card's licence is read and found permissive. AudioSet's 2017
  ontology has "Afrobeat" but no "Amapiano", so the Amapiano template maps the nearest labels
  (House music, Electronic dance music, Deep house, Afrobeat). The tagger runs on the Space
  only; in CI and offline the default template (pop) is used and run.json says why. The listener's
  choice always wins.
- **Templates** (`configs/templates/*.json`): Afrobeats, Amapiano, Hip-hop and rap, R&B and soul,
  Gospel and choir, House and EDM, Pop, Rock, Acoustic, Classical. Each sets, per object, the
  source part, azimuth, elevation, distance, spread, room send, original blend, protection,
  optional wide setting and motion, plus the bed and the openness per section, each with its
  reasoning. The lead vocal, the bass and the kit are protected in every template.
- **plan.json** (`schemas/plan.schema.json`, version 2) is the contract: `build_plan` is pure and
  deterministic (equal inputs give byte-identical plans, tested), `validate_plan` checks the
  schema, the space, the source parts and that no protected object moves, and the pipeline
  renders a given plan instead of building one, which is what /rerender uses.

## Sources

ESTABLISHED: Ellis 2007; Foote 2000; Bock and Widmer 2013 (detection function family); the
AudioSet ontology as listed by the model's label set (checked at run time). The model card's
licence is read at run time rather than assumed. SPECULATIVE: every template value; they follow
common mixing practice for each genre as described in each `why`, and the listening test decides.
