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

## The streaming catalogue (metadata only)

| Data | What is used | Licence | Where it comes from | Notes |
|---|---|---|---|---|
| Openly licensed music, listed in `configs/catalogue/seed.json` (built 2026-11-25T00:55:14Z: 115 tracks, 68 CC BY-SA 3.0, 33 CC BY 3.0, 8 CC BY-SA 2.0, 4 CC BY-SA 2.5, 2 CC BY 2.0) | Title, creator, links, licence and attribution line of each track; the audio is streamed from its source and never stored here | CC BY and CC BY-SA only (CC0 and public domain are accepted too); every NoDerivatives licence is excluded, and NonCommercial ones are off by default (`decision 0028`) | Openverse (api.openverse.org) searches Jamendo's catalogue; Jamendo's own API v3 is used when the owner sets `JAMENDO_CLIENT_ID`; an Internet Archive adapter exists but its audio hosts could not be checked from the build environment, so none of its tracks is in the seed | Every listed track's audio URL answered with audio when the seed was built. Shelves: afrobeats 14, amapiano 8, hiphop 12, rnb_soul 12, gospel 8, house_electronic 14, lofi 12, cinematic 12, acoustic 12, classical 12, made_for_spatial 12. |
| Pre-rendered spatial versions | Opus segments, plan and report of the curated tracks (first five of each shelf) | The licence of the source track; a render of a CC BY-SA track is CC BY-SA | The dataset repo `danieltesh/soundstage-catalogue`, written by the `catalogue` workflow or `scripts/render_catalogue.py` | Each folder holds the licence and the attribution line beside the audio |

None of this audio is stored in this repository.
