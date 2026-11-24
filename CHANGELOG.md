# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Repository structure, documentation, decision records, JSON schemas, tests and CI.
- Lite renderer (`stage.render.render_stereo`) and `scripts/render_clip.py` for headphone A/B clips.
- The project is called SoundStage (the Python package stays `stage`). Decision 0009.
- Fidelity report for every render (`report.json`, decision 0011): BS.1770-4 loudness, true peak,
  downmix, mono sum, low end, timestamped artifact flags and a verdict with reasons; thresholds in
  `configs/thresholds/guard.json`. PR #9's checks and decision (now 0010) are on main.
- `start="auto"`: the excerpt starts at the loudest window of the track by default.
- v2 engine, Phase 1: measured SADIE II KU100 HRTF pack built on GitHub Actions
  (`tools/hrtf-pack`), spherical interpolation, six binaural spaces (`configs/spaces`), zero-phase
  bass bypass, timbre and loudness matching. `space:<name>` profiles; `space:studio` is the
  default. Decisions 0012 to 0014.
- `stage.pipeline.run` with a per-stage run report (`schemas/run.schema.json`), Lite fallback and
  24-bit FLAC outputs; `scripts/process_track.py`.
- `stage.separation.demucs_sep` (optional `separation` extra: torch, demucs).
- `stage.guard.levels`, shared by `render_clip.py` and `make_abx.py`.
- `stage.service` and the Gradio backend in `space/`, with a Space deploy workflow.
- The web listening bench in `web/`.
