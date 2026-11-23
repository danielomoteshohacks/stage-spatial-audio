# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Repository structure, documentation, decision records, JSON schemas, tests and CI.
- Lite renderer (`stage.render.render_stereo`) and `scripts/render_clip.py` for headphone A/B clips.
- The project is called SoundStage (the Python package stays `stage`). Decision 0009.
- `stage.pipeline.run` with a per-stage run report (`schemas/run.schema.json`), Lite fallback and
  24-bit FLAC outputs; `scripts/process_track.py`.
- `stage.separation.demucs_sep` (optional `separation` extra: torch, demucs).
- `stage.guard.levels`, shared by `render_clip.py` and `make_abx.py`.
- `stage.service` and the Gradio backend in `space/`, with a Space deploy workflow.
- The web listening bench in `web/`.
