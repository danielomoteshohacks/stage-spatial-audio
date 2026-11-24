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

Audio for the separator's training (MUSDB18-HQ and any extra music) is listed in
`training/README.md` with its licence, and is never stored in this repository.
