# scripts

Helper scripts: download and verify models and datasets against their manifests, regenerate golden
files, run the full evaluation.

- `analyze_clip.py`: where the stereo analysis finds the primary sound.
- `render_clip.py`: render an excerpt with the Lite renderer and write an A/B pair of 24-bit WAVs.
- `make_abx.py`: blind test of the spatialisation profiles; see `experiments/ABX.md`.

Status: the rest (model and dataset download and verification, golden files, full evaluation) is planned.
