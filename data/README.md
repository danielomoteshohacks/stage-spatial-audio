# data

Audio is **never committed**. Keep local files here (they are ignored by Git) and record every
file in a manifest: source, licence, and what it is used for. Only music you own, have written
permission to use, or that carries an open licence may be used. Never use Spotify audio, previews or
API data.

See `manifest.example.csv` for the format.

## Datasets used by the engine

| Dataset | What is used | Licence | Where it is fetched | Notes |
|---|---|---|---|---|
| SADIE II (University of York) | Subject D1 (KU100): 8802 HRIRs at 48 kHz, 50 studio BRIRs | Apache-2.0, checked in the Zenodo record and the SOFA file | GitHub Actions (`hrtf-pack.yml`) from Zenodo; the Space from the GitHub release | Attribution in `models/MANIFEST.md` and the app's credits |

| MUSDB18-HQ (Rafii et al. 2019, Zenodo 10.5281/zenodo.3338373) | 100 training and 50 test tracks with stems | Research use only; tracks under their own, mostly non-commercial, licences | Kaggle, from Zenodo or an attached Kaggle copy | Separator training and evaluation (`training/README.md`) |
| Extra music for teacher pseudo-labels | Only music the owner has the right to use | The owner's rights | A private Kaggle dataset | Optional |

None of this audio is stored in this repository.
