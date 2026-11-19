# scripts

Helper scripts: download and verify models and datasets against their manifests, regenerate golden
files, run the full evaluation.

- `analyze_clip.py`: where the stereo analysis finds the primary sound.
- `render_clip.py`: render an excerpt with the Lite renderer and write an A/B pair of 24-bit WAVs.
  `--guard` prints the fidelity-guard report.
- `measure_sector_sum.py`: magnitude response of the sector chain for fixed pan positions, and
  the comb between neighbouring sectors; see `docs/decisions/0009-sector-sum-comb.md`.
- `make_abx.py`: blind test of the spatialisation profiles; see `experiments/ABX.md`.

Status: the rest (model and dataset download and verification, golden files, full evaluation) is planned.
