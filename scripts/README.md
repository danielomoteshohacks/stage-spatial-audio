# scripts

Helper scripts: download and verify models and datasets against their manifests, regenerate golden
files, run the full evaluation.

- `analyze_clip.py`: where the stereo analysis finds the primary sound.
- `render_clip.py`: render an excerpt with the Lite renderer and write an A/B pair of 24-bit WAVs.
- `make_abx.py`: blind test of the spatialisation profiles; see `experiments/ABX.md`.
- `process_track.py`: run the full pipeline (Lite or stems) on one track and print a per-stage
  summary; writes 24-bit FLAC and `run.json`.
- `make_test_signal.py`: write a generated test track (tones and noise bursts panned left, centre
  and right) for checking that the pipeline and the backend run end to end.

Status: the rest (model and dataset download and verification, golden files, full evaluation) is planned.
